"""
api/read_api.py

Read-only API server. Serves stored metrics data to the frontend.
Has no write endpoints — that is ingest_api.py's responsibility.

The SSE endpoint (/stream) pushes updates to connected clients whenever new
data is available. It uses one of two mechanisms depending on how the server
is started:

  - When started via 'python server.py both': waits on a shared
    threading.Event that IngestAPI sets after each commit — push is instant.

  - When started standalone via 'python server.py read': polls SystemState
    in the database every second — push has up to 1 second of latency.

Endpoints:
    GET /hello
    GET /aggregators
    GET /aggregators?guid=<guid>
    GET /devices?aggregator_guid=<guid>
    GET /devices?aggregator_guid=<guid>&name=<n>
    GET /metrics?guid=<guid>&device_name=<n>&utc_date_min=<datetime>&utc_date_max=<datetime>
    GET /pc_info
    GET /pokemon_info?format=<format>&type=<mons|move>
    GET /stream         — SSE push endpoint for the frontend
"""

import sys
import json
import logging
import threading
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from flask import Flask, request, Response, stream_with_context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from collectors.metrics_datamodel import (
    DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
)
from models import Aggregator, Device, DeviceMetricType, MetricSnapshot, MetricValue, SystemState
from collectors import PCInfo
from collectors import PokemonInfo

# How often the SSE generator polls the database when no threading.Event is
# available (standalone deployment). Lower = more responsive, higher = less
# DB load.
SSE_POLL_INTERVAL  = 1   # seconds
HEARTBEAT_INTERVAL = 15  # seconds between keepalive pings to the client


class ReadAPI:
    def __init__(self):
        self.config        = Config(__file__)
        self.logger        = logging.getLogger(__name__)
        self.webserver     = Flask(__name__)
        self.engine        = create_engine(self.config.database.connection_string)
        self._update_event: threading.Event | None = None
        self._setup_routes()
        self.logger.debug("ReadAPI initialized")

    def set_update_event(self, event: threading.Event):
        """Provide the shared threading.Event that the SSE generator will wait
        on instead of polling the database.

        IngestAPI sets this same event after every successful commit, waking
        all SSE generators simultaneously so they push to their clients
        immediately with no polling delay.

        This is called by server.py when running both APIs in the same process.
        If never called, the SSE generator falls back to polling SystemState.

        Args:
            event: The shared Event instance created in server.py
        """
        self._update_event = event
        self.logger.debug("ReadAPI: shared update event registered")

    def _setup_routes(self):
        self.webserver.route("/hello")(self.hello)
        self.webserver.route("/aggregators",  methods=['GET'])(self.get_aggregators)
        self.webserver.route("/devices",      methods=['GET'])(self.get_devices)
        self.webserver.route("/metrics",      methods=['GET'])(self.get_metrics)
        self.webserver.route("/pc_info",      methods=['GET'])(self.get_pc_info)
        self.webserver.route("/pokemon_info", methods=['GET'])(self.get_pokemon_info)
        self.webserver.route("/stream",       methods=['GET'])(self.stream)
        self.webserver.route("/trainer_info", methods=['GET'])(self.get_trainer_info)
        self.webserver.route("/trainers", methods=['GET'])(self.get_trainers)

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Routes
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def hello(self):
        return {'message': 'Read API is running. See /metrics, /aggregators, /devices, /pc_info, /pokemon_info, /stream.'}

    def stream(self):
        """Server-Sent Events endpoint.
        GET /stream
        """
        return Response(
            stream_with_context(self._sse_generator()),
            mimetype='text/event-stream',
            headers={
                'X-Accel-Buffering':           'no',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control':               'no-cache',
            }
        )

    def get_aggregators(self):
        """Return all aggregators, or a single one by GUID.
        GET /aggregators
        GET /aggregators?guid=<guid>
        """
        guid    = request.args.get('guid')
        session = Session(self.engine)
        try:
            if guid:
                aggregator = session.query(Aggregator).filter_by(guid=guid).first()
                if not aggregator:
                    return {'status': 'error', 'message': f'No aggregator found with GUID {guid}'}, 404
                aggregators = [aggregator]
            else:
                aggregators = session.query(Aggregator).all()

            result = [
                DTO_Aggregator(guid=a.guid, name=a.name, devices=[]).to_dict()
                for a in aggregators
            ]
            return {'status': 'success', 'aggregators': result}, 200

        except Exception as e:
            self.logger.exception("Error in get_aggregators: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_devices(self):
        """Return devices for an aggregator, optionally filtered by name.
        GET /devices?aggregator_guid=<guid>
        GET /devices?aggregator_guid=<guid>&name=<n>
        """
        aggregator_guid = request.args.get('aggregator_guid')
        if not aggregator_guid:
            return {'status': 'error', 'message': 'aggregator_guid is required'}, 400

        name    = request.args.get('name')
        session = Session(self.engine)
        try:
            query = session.query(Device).join(Aggregator).filter(
                Aggregator.guid == aggregator_guid
            )
            if name:
                query = query.filter(Device.name == name)

            devices = query.all()
            if name and not devices:
                return {'status': 'error', 'message': f'No device "{name}" found for aggregator {aggregator_guid}'}, 404

            result = [DTO_Device(name=d.name, data_snapshots=[]) for d in devices]
            return {'status': 'success', 'devices': result}, 200

        except Exception as e:
            self.logger.exception("Error in get_devices: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_metrics(self):
        """Return stored metric values, with optional filters.
        GET /metrics
        GET /metrics?guid=<guid>&device_name=<n>&utc_date_min=<Y-m-d H:M:S>&utc_date_max=<Y-m-d H:M:S>
        """
        session = Session(self.engine)
        try:
            guid         = request.args.get('guid')
            device_name  = request.args.get('device_name')
            utc_date_min = datetime.strptime(request.args['utc_date_min'], '%Y-%m-%d %H:%M:%S') if request.args.get('utc_date_min') else None
            utc_date_max = datetime.strptime(request.args['utc_date_max'], '%Y-%m-%d %H:%M:%S') if request.args.get('utc_date_max') else None

            return {'status': 'success', 'aggregators': self._query_metrics(session, guid, device_name, utc_date_min, utc_date_max)}, 200

        except Exception as e:
            self.logger.exception("Error in get_metrics: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_pc_info(self):
        """Return the latest PC hardware snapshot from the database.
        GET /pc_info
        """
        session = Session(self.engine)
        try:
            # Find the Betty_III device under its aggregator
            device = (
                session.query(Device)
                .join(Aggregator)
                .filter(Aggregator.guid == str(PCInfo.aggregator_guid))
                .first()
            )
            if not device:
                return {'status': 'error', 'message': 'No PC data found in database'}, 404

            # Get the most recent snapshot
            latest_snapshot = (
                session.query(MetricSnapshot)
                .filter_by(device_id=device.device_id)
                .order_by(MetricSnapshot.client_utc_timestamp_epoch.desc())
                .first()
            )
            if not latest_snapshot:
                return {'status': 'error', 'message': 'No snapshots found'}, 404

            # Rebuild flat dict of metric name -> value
            metric_values = (
                session.query(MetricValue)
                .join(DeviceMetricType)
                .filter(MetricValue.metric_snapshot_id == latest_snapshot.metric_snapshot_id)
                .all()
            )

            data = {mv.device_metric_type.name: mv.value for mv in metric_values}

            return {'status': 'success', 'data': data}, 200

        except Exception as e:
            self.logger.exception("Error in get_pc_info: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_pokemon_info(self):
        """Return Pokémon usage counts summed across all stored snapshots.
        GET /pokemon_info?format=gen9ou&type=mons
        """
        fmt  = request.args.get('format', 'gen9ou')
        kind = request.args.get('type', 'mons')
        session = Session(self.engine)
        try:
            # Find the device matching the requested format under the PokemonShowdown aggregator
            device = (
                session.query(Device)
                .join(Aggregator)
                .filter(
                    Aggregator.guid == 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
                    Device.name == fmt
                )
                .first()
            )
            if not device:
                return {'status': 'error', 'message': f'No data found for format {fmt}'}, 404

            # Sum metric values across ALL snapshots for this device, grouped by metric name
            from sqlalchemy import func

            results = (
                session.query(
                    DeviceMetricType.name,
                    func.sum(MetricValue.value).label('total')
                )
                .join(MetricValue, DeviceMetricType.device_metric_type_id == MetricValue.device_metric_type_id)
                .join(MetricSnapshot, MetricValue.metric_snapshot_id == MetricSnapshot.metric_snapshot_id)
                .filter(MetricSnapshot.device_id == device.device_id)
                .group_by(DeviceMetricType.name)
                .order_by(func.sum(MetricValue.value).desc())
                .all()
            )

            if not results:
                return {'status': 'error', 'message': f'No snapshots found for format {fmt}'}, 404

            data = {name: int(total) for name, total in results}

            return {'status': 'success', 'format': fmt, 'type': kind, 'data': data}, 200

        except Exception as e:
            self.logger.exception("Error in get_pokemon_info: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_trainer_info(self):
        """Return a trainer's current party grouped by generation.
        GET /trainer_info?trainer=DavidM
        """
        trainer_name = request.args.get('trainer')
        if not trainer_name:
            return {'status': 'error', 'message': 'trainer parameter is required'}, 400

        session = Session(self.engine)
        try:
            # Find the device matching the trainer under the mobileapp aggregator
            device = (
                session.query(Device)
                .join(Aggregator)
                .filter(
                    Aggregator.guid == 'b2c3d4e5-f6a7-8901-bcde-f12345678901',
                    Device.name == trainer_name
                )
                .first()
            )
            if not device:
                return {'status': 'error', 'message': f'No data found for trainer {trainer_name}'}, 404

            # Get the most recent snapshot — party is current state, not cumulative
            latest_snapshot = (
                session.query(MetricSnapshot)
                .filter_by(device_id=device.device_id)
                .order_by(MetricSnapshot.client_utc_timestamp_epoch.desc())
                .first()
            )
            if not latest_snapshot:
                return {'status': 'error', 'message': f'No snapshots found for trainer {trainer_name}'}, 404

            # Pull metric values for the latest snapshot
            metric_values = (
                session.query(MetricValue)
                .join(DeviceMetricType)
                .filter(MetricValue.metric_snapshot_id == latest_snapshot.metric_snapshot_id)
                .all()
            )

            # Reconstruct { generation: [pokemon_names] } from "gen|pokemon" metric keys
            party = {}
            for mv in metric_values:
                parts = mv.device_metric_type.name.split('|')
                gen   = parts[0]
                name  = parts[1] if len(parts) > 1 else 'unknown'
                if gen not in party:
                    party[gen] = []
                party[gen].append(name)

            return {
                'status':  'success',
                'trainer': trainer_name,
                'party':   party,
            }, 200

        except Exception as e:
            self.logger.exception("Error in get_trainer_info: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()
    
    def get_trainers(self):
        """Return a list of all trainer names stored under the mobileapp aggregator.
        GET /trainers
        """
        session = Session(self.engine)
        try:
            devices = (
                session.query(Device)
                .join(Aggregator)
                .filter(Aggregator.guid == 'b2c3d4e5-f6a7-8901-bcde-f12345678901')
                .all()
            )
            if not devices:
                return {'status': 'error', 'message': 'No trainers found'}, 404

            trainers = [d.name for d in devices]

            return {
                'status':   'success',
                'trainers': trainers,
            }, 200

        except Exception as e:
            self.logger.exception("Error in get_trainers: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()


    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # SSE internals
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _sse_generator(self):
        """Generator that drives the SSE stream for one connected client.

        Uses one of two strategies to detect new data:

        Event mode (both APIs in same process):
            Calls event.wait(timeout=HEARTBEAT_INTERVAL). The event is set by
            IngestAPI._signal_update() the moment a snapshot is committed, so
            this wakes up and pushes to the client instantly. If nothing
            arrives within HEARTBEAT_INTERVAL seconds, a heartbeat is sent
            instead and the wait restarts.

        Poll mode (standalone deployment, no shared event):
            Sleeps SSE_POLL_INTERVAL seconds, then reads SystemState from the
            database. If last_updated has changed since the last push, new
            data is fetched and pushed. A heartbeat is sent when HEARTBEAT_INTERVAL
            seconds pass without a push.

        Yields SSE-formatted byte strings.
        """
        self.logger.info("SSE client connected (mode: %s)",
                         "event" if self._update_event else "poll")
        last_heartbeat = time.time()

        try:
            if self._update_event is not None:
                yield from self._sse_event_mode(last_heartbeat)
            else:
                yield from self._sse_poll_mode(last_heartbeat)
        except GeneratorExit:
            self.logger.info("SSE client disconnected")

    def _sse_event_mode(self, last_heartbeat: float):
        """SSE loop used when a shared threading.Event is available.

        Waits on the event with a timeout equal to HEARTBEAT_INTERVAL. When
        IngestAPI sets the event, this wakes immediately, fetches fresh
        metrics, pushes them to the client, then clears the event and waits
        again. If the timeout expires with no event, a heartbeat is sent.

        Args:
            last_heartbeat: epoch time of the last heartbeat, used to track
                            the 15-second keepalive interval on first entry
        """
        while True:
            triggered = self._update_event.wait(timeout=HEARTBEAT_INTERVAL)

            if triggered:
                # IngestAPI committed new data — clear the flag and push
                self._update_event.clear()
                try:
                    yield self._sse_event('metrics', self._latest_metrics_payload())
                    self.logger.debug("SSE metrics event sent (event mode)")
                except Exception as e:
                    self.logger.exception("SSE failed to fetch metrics: %s", str(e))
                    yield self._sse_event('error', {'message': str(e)})
            else:
                # Timeout — no new data, send keepalive
                yield self._sse_event('heartbeat', {})
                self.logger.debug("SSE heartbeat sent")

    def _sse_poll_mode(self, last_heartbeat: float):
        """SSE loop used when no threading.Event is available (standalone).

        Polls SystemState.last_updated every SSE_POLL_INTERVAL seconds. Pushes
        a metrics event when the value changes, and a heartbeat event when
        HEARTBEAT_INTERVAL seconds pass without a push.

        Args:
            last_heartbeat: epoch time of the last heartbeat sent
        """
        last_seen_ts = None

        while True:
            time.sleep(SSE_POLL_INTERVAL)
            current_ts = self._get_last_updated()

            if current_ts != last_seen_ts:
                last_seen_ts   = current_ts
                last_heartbeat = time.time()
                try:
                    yield self._sse_event('metrics', self._latest_metrics_payload())
                    self.logger.debug("SSE metrics event sent (poll mode)")
                except Exception as e:
                    self.logger.exception("SSE failed to fetch metrics: %s", str(e))
                    yield self._sse_event('error', {'message': str(e)})

            elif time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                last_heartbeat = time.time()
                yield self._sse_event('heartbeat', {})
                self.logger.debug("SSE heartbeat sent")

    def _get_last_updated(self) -> int | None:
        """Read SystemState.last_updated from the database.

        Opens a fresh session each call so SQLAlchemy's cache never returns a
        stale value from a previous read in this process.

        Returns:
            The epoch timestamp as an int, or None if no snapshots have been
            ingested yet.
        """
        session = Session(self.engine)
        try:
            state = session.query(SystemState).filter_by(id=1).first()
            return state.last_updated if state else None
        finally:
            session.close()

    def _latest_metrics_payload(self) -> dict:
        """Fetch all current metrics from the database and return them as a
        plain dict for JSON serialisation in an SSE event.

        Returns the same shape as GET /metrics with no filters — all
        aggregators, all devices, all latest values.
        """
        session = Session(self.engine)
        try:
            return {
                'status':      'success',
                'aggregators': self._query_metrics(session, None, None, None, None)
            }
        finally:
            session.close()

    @staticmethod
    def _sse_event(event_name: str, data: dict) -> bytes:
        """Format a dict as a single SSE event and return it as UTF-8 bytes.

        SSE wire format (each field on its own line, blank line terminates):
            event: <name>\\n
            data: <json>\\n
            \\n

        The trailing blank line is mandatory — without it the browser will not
        fire the event.

        Args:
            event_name: Event type string seen by the frontend listener
            data:       Dict to serialise as the event payload

        Returns:
            UTF-8 encoded bytes ready to yield from the generator
        """
        return f"event: {event_name}\ndata: {json.dumps(data)}\n\n".encode('utf-8')

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Shared query helper
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _query_metrics(self, session, guid, device_name, utc_date_min, utc_date_max) -> list:
        """Build and execute a metrics query, returning a list of DTO_Aggregator
        dicts. Shared between get_metrics() and the SSE push so both always
        return data in the same shape.

        Args:
            session:      Active SQLAlchemy session
            guid:         Filter by aggregator GUID, or None for all
            device_name:  Filter by device name, or None for all
            utc_date_min: Earliest timestamp to include, or None
            utc_date_max: Latest timestamp to include, or None
        """
        query = (
            session.query(MetricValue)
            .join(MetricSnapshot, MetricValue.metric_snapshot_id == MetricSnapshot.metric_snapshot_id)
            .join(Device,         MetricSnapshot.device_id        == Device.device_id)
            .join(Aggregator,     Device.aggregator_id            == Aggregator.aggregator_id)
        )
        if guid:
            query = query.filter(Aggregator.guid == guid)
        if device_name:
            query = query.filter(Device.name == device_name)
        if utc_date_min:
            query = query.filter(MetricSnapshot.client_utc_timestamp_epoch >= int(utc_date_min.timestamp()))
        if utc_date_max:
            query = query.filter(MetricSnapshot.client_utc_timestamp_epoch <= int(utc_date_max.timestamp()))

        aggregator_dtos = {}
        for mv in query.all():
            device     = session.query(Device).filter_by(device_id=mv.device_metric_type.device_id).first()
            aggregator = session.query(Aggregator).filter_by(aggregator_id=device.aggregator_id).first()

            agg_dto = aggregator_dtos.setdefault(
                aggregator.guid,
                DTO_Aggregator(guid=aggregator.guid, name=aggregator.name, devices=[])
            )
            dev_dto = next((d for d in agg_dto.devices if d.name == device.name), None)
            if not dev_dto:
                dev_dto = DTO_Device(name=device.name, data_snapshots=[])
                agg_dto.devices.append(dev_dto)

            snapshot_ts = datetime.fromtimestamp(mv.metric_snapshot.client_utc_timestamp_epoch)
            ds_dto = next(
                (ds for ds in dev_dto.data_snapshots
                 if ds.timestamp_utc == snapshot_ts
                 and ds.timezone_mins == mv.metric_snapshot.client_timezone_mins),
                None
            )
            if not ds_dto:
                ds_dto = DTO_DataSnapshot(
                    timestamp_utc=snapshot_ts,
                    timezone_mins=mv.metric_snapshot.client_timezone_mins,
                    metrics=[]
                )
                dev_dto.data_snapshots.append(ds_dto)

            ds_dto.metrics.append(DTO_Metric(name=mv.device_metric_type.name, value=mv.value))

        return list(aggregator_dtos.values())

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Entry point
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def run(self) -> int:
        try:
            self.logger.info("Starting ReadAPI on port %s", self.config.read_api.port)
            self.webserver.run(
                debug=self.config.read_api.debug,
                port=self.config.read_api.port,
                threaded=True   # each SSE client holds its own thread
            )
            return 0
        except Exception as e:
            self.logger.exception("ReadAPI failed: %s", str(e))
            return 1


def main() -> int:
    return ReadAPI().run()


if __name__ == "__main__":
    sys.exit(main())
else:
    _app = ReadAPI()
    app  = _app.webserver