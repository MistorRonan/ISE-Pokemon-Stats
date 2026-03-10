"""
api/ingest_api.py

Write-only API server. Receives snapshots from agents and persists them to
the database. Has no read endpoints — that is read_api.py's responsibility.

After every successful snapshot write, signals the read API that new data is
available via one of two mechanisms depending on how the server is started:

  - When started via 'python server.py both': fires a shared threading.Event
    that the read API's SSE generator is waiting on — push is instant.

  - When started standalone via 'python server.py ingest': falls back to
    updating SystemState in the database, which the read API polls instead.

Endpoints:
    POST /aggregator_snapshots  — receive and store a DTO_Aggregator snapshot
"""

import sys
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from flask import Flask, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from collectors.metrics_datamodel import DTO_Aggregator
from models import Aggregator, Device, DeviceMetricType, MetricSnapshot, MetricValue, SystemState


class IngestAPI:
    def __init__(self):
        self.config        = Config(__file__)
        self.logger        = logging.getLogger(__name__)
        self.webserver     = Flask(__name__)
        self.engine        = create_engine(self.config.database.connection_string)
        self._update_event: threading.Event | None = None
        self._setup_routes()
        self.logger.debug("IngestAPI initialized")

    def set_update_event(self, event: threading.Event):
        """Provide the shared threading.Event that IngestAPI will set after
        every successful snapshot write. ReadAPI waits on the same event
        object and pushes to SSE clients the moment it fires.

        This is called by server.py when running both APIs in the same process.
        If never called, IngestAPI falls back to updating SystemState in the
        database as a signal instead.

        Args:
            event: The shared Event instance created in server.py
        """
        self._update_event = event
        self.logger.debug("IngestAPI: shared update event registered")

    def _setup_routes(self):
        self.webserver.route("/aggregator_snapshots", methods=['POST'])(self.upload_snapshot)

    def upload_snapshot(self):
        """Receive a DTO_Aggregator JSON snapshot from an agent and write it to
        the database. Creates aggregator, device, and metric type rows on first
        sight; always creates a new snapshot and metric value rows.

        After a successful commit, signals the read API via threading.Event
        (if available) or by updating SystemState in the database.
        """
        session = None
        try:
            self.logger.info("Deserializing incoming snapshot")
            data           = request.get_json()
            dto_aggregator = DTO_Aggregator.from_dict(data)
            self.logger.info("Snapshot deserialized: %s", dto_aggregator)

            session = Session(self.engine)

            # Find or create aggregator
            aggregator = session.query(Aggregator).filter_by(
                guid=str(dto_aggregator.guid)
            ).first()
            if not aggregator:
                aggregator = Aggregator(
                    guid=str(dto_aggregator.guid),
                    name=dto_aggregator.name
                )
                session.add(aggregator)
                session.flush()

            for dto_device in dto_aggregator.devices:
                device = session.query(Device).filter_by(
                    aggregator_id=aggregator.aggregator_id,
                    name=dto_device.name
                ).first()

                if not device:
                    max_ordinal = session.query(Device).filter_by(
                        aggregator_id=aggregator.aggregator_id
                    ).count()
                    device = Device(
                        aggregator_id=aggregator.aggregator_id,
                        name=dto_device.name,
                        ordinal=max_ordinal
                    )
                    session.add(device)
                    session.flush()

                now_utc = datetime.now(timezone.utc)
                for dto_snapshot in dto_device.data_snapshots:
                    snapshot = MetricSnapshot(
                        device_id=device.device_id,
                        client_utc_timestamp_epoch=int(dto_snapshot.timestamp_utc.timestamp()),
                        client_timezone_mins=dto_snapshot.timezone_mins,
                        server_utc_timestamp_epoch=int(now_utc.timestamp()),
                        server_timezone_mins=int(
                            now_utc.astimezone().utcoffset().total_seconds() / 60
                        )
                    )
                    session.add(snapshot)
                    session.flush()

                    for dto_metric in dto_snapshot.metrics:
                        metric_type = session.query(DeviceMetricType).filter_by(
                            device_id=device.device_id,
                            name=dto_metric.name
                        ).first()
                        if not metric_type:
                            metric_type = DeviceMetricType(
                                device_id=device.device_id,
                                name=dto_metric.name
                            )
                            session.add(metric_type)
                            session.flush()

                        session.add(MetricValue(
                            metric_snapshot_id=snapshot.metric_snapshot_id,
                            device_metric_type_id=metric_type.device_metric_type_id,
                            value=float(dto_metric.value)
                        ))

            # Always update SystemState so standalone read_api can poll it
            self._update_system_state(session)

            session.commit()
            self.logger.info("Snapshot stored successfully")

            # Signal the read API. If a shared Event is available (both APIs
            # running in the same process) this fires instantly. Otherwise the
            # read API falls back to polling SystemState which was updated above.
            self._signal_update()

            return {'status': 'success', 'message': 'Snapshot stored successfully'}, 201

        except Exception as e:
            if session:
                try:
                    session.rollback()
                    session.close()
                except Exception:
                    pass
            self.logger.exception("Error storing snapshot: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            if session:
                session.close()

    def _signal_update(self):
        """Notify the read API that new data has been committed.

        If a shared threading.Event was provided via set_update_event(), sets
        it so the read API's SSE generator wakes up immediately. The event is
        cleared by the read API after it wakes, ready for the next snapshot.

        If no event is available (standalone process), the read API will detect
        the update via SystemState polling instead — no action needed here.
        """
        if self._update_event is not None:
            self._update_event.set()
            self.logger.debug("IngestAPI: update event fired")

    def _update_system_state(self, session: Session):
        """Update or create the single SystemState row with the current UTC
        timestamp. Included in the same transaction as the snapshot write so
        it rolls back automatically if the write fails.

        Used as a fallback signal for standalone read_api deployments that
        cannot share a threading.Event with this process.

        Args:
            session: The active SQLAlchemy session for the current request
        """
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        state     = session.query(SystemState).filter_by(id=1).first()
        if state:
            state.last_updated = now_epoch
        else:
            session.add(SystemState(id=1, last_updated=now_epoch))

    def run(self) -> int:
        try:
            self.logger.info("Starting IngestAPI on port %s", self.config.ingest_api.port)
            self.webserver.run(host='0.0.0.0',debug=self.config.ingest_api.debug, port=self.config.ingest_api.port)
            return 0
        except Exception as e:
            self.logger.exception("IngestAPI failed: %s", str(e))
            return 1


def main() -> int:
    return IngestAPI().run()


if __name__ == "__main__":
    sys.exit(main())
else:
    _app = IngestAPI()
    app  = _app.webserver
