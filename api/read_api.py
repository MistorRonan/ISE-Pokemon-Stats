"""
api/read_api.py

Read-only API server. Serves stored metrics data to the frontend.
Has no write endpoints — that is ingest_api.py's responsibility.

Endpoints:
    GET /hello
    GET /aggregators
    GET /aggregators?guid=<guid>
    GET /devices?aggregator_guid=<guid>
    GET /devices?aggregator_guid=<guid>&name=<n>
    GET /metrics?guid=<guid>&device_name=<n>&utc_date_min=<datetime>&utc_date_max=<datetime>
    GET /pc_info        — live hardware snapshot from this machine
    GET /pokemon_info?format=<format>&type=<mons|move>  — live Showdown replay stats

Run this process independently of ingest_api.py on its own configured port.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from flask import Flask, request

# Add the project root to sys.path so imports resolve correctly when this
# file is run from inside the api/ folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib_config.config import Config
from lib_metrics_datamodel.metrics_datamodel import (
    DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
)
from models import Aggregator, Device, DeviceMetricType, MetricSnapshot, MetricValue
import PCInfo
import PokemonInfo


class ReadAPI:
    def __init__(self):
        self.config = Config(__file__)
        self.logger = logging.getLogger(__name__)
        self.webserver = Flask(__name__)
        self.engine = create_engine(self.config.database.connection_string)
        self._setup_routes()
        self.logger.debug("ReadAPI initialized")

    def _setup_routes(self):
        self.webserver.route("/hello")(self.hello)
        self.webserver.route("/aggregators",  methods=['GET'])(self.get_aggregators)
        self.webserver.route("/devices",      methods=['GET'])(self.get_devices)
        self.webserver.route("/metrics",      methods=['GET'])(self.get_metrics)
        self.webserver.route("/pc_info",      methods=['GET'])(self.get_pc_info)
        self.webserver.route("/pokemon_info", methods=['GET'])(self.get_pokemon_info)

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Routes
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def hello(self):
        return {'message': 'Read API is running. See /metrics, /aggregators, /devices, /pc_info, /pokemon_info.'}

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

            # Build DTO hierarchy from flat query results
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

            return {'status': 'success', 'aggregators': list(aggregator_dtos.values())}, 200

        except Exception as e:
            self.logger.exception("Error in get_metrics: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_pc_info(self):
        """Return a live hardware snapshot from this machine.
        GET /pc_info
        """
        try:
            return {'status': 'success', 'data': PCInfo.collect()}, 200
        except Exception as e:
            self.logger.exception("Error in get_pc_info: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500

    def get_pokemon_info(self):
        """Return live Pokémon usage/move counts from recent Showdown replays.
        GET /pokemon_info?format=gen9ou&type=mons
        """
        try:
            fmt   = request.args.get('format', 'gen9ou')
            kind  = request.args.get('type', 'mons')
            data  = PokemonInfo.collect(f"{fmt}|{kind}")
            if data is None:
                return {'status': 'error', 'message': f'No replay data returned for format {fmt}'}, 404
            return {'status': 'success', 'format': fmt, 'type': kind, 'data': data}, 200
        except Exception as e:
            self.logger.exception("Error in get_pokemon_info: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Entry point
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def run(self) -> int:
        try:
            self.logger.info("Starting ReadAPI on port %s", self.config.read_api.port)
            self.webserver.run(debug=self.config.read_api.debug, port=self.config.read_api.port)
            return 0
        except Exception as e:
            self.logger.exception("ReadAPI failed: %s", str(e))
            return 1


def main() -> int:
    return ReadAPI().run()


if __name__ == "__main__":
    sys.exit(main())
else:
    # WSGI entry point
    _app = ReadAPI()
    app = _app.webserver
