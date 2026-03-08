"""
api/ingest_api.py

Write-only API server. Receives snapshots from agents and persists them to
the database. Has no read endpoints — that is read_api.py's responsibility.

Endpoints:
    POST /aggregator_snapshots  — receive and store a DTO_Aggregator snapshot

Run this process independently of read_api.py on its own configured port.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from flask import Flask, request

# Add the project root to sys.path so imports resolve correctly when this
# file is run from inside the api/ folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib_config.config import Config
from lib_metrics_datamodel.metrics_datamodel import DTO_Aggregator
from models import Aggregator, Device, DeviceMetricType, MetricSnapshot, MetricValue


class IngestAPI:
    def __init__(self):
        self.config = Config(__file__)
        self.logger = logging.getLogger(__name__)
        self.webserver = Flask(__name__)
        self.engine = create_engine(self.config.database.connection_string)
        self._setup_routes()
        self.logger.debug("IngestAPI initialized")

    def _setup_routes(self):
        self.webserver.route("/aggregator_snapshots", methods=['POST'])(self.upload_snapshot)

    def upload_snapshot(self):
        """Receive a DTO_Aggregator JSON snapshot from an agent and write it to
        the database. Creates aggregator, device, and metric type rows on first
        sight; always creates a new snapshot and metric value rows.
        """
        session = None
        try:
            self.logger.info("Deserializing incoming snapshot")
            data = request.get_json()
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

            # Process each device
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

                # Create a snapshot row for each incoming data snapshot
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

            session.commit()
            self.logger.info("Snapshot stored successfully")
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

    def run(self) -> int:
        try:
            self.logger.info("Starting IngestAPI on port %s", self.config.ingest_api.port)
            self.webserver.run(debug=self.config.ingest_api.debug, port=self.config.ingest_api.port)
            return 0
        except Exception as e:
            self.logger.exception("IngestAPI failed: %s", str(e))
            return 1


def main() -> int:
    return IngestAPI().run()


if __name__ == "__main__":
    sys.exit(main())
else:
    # WSGI entry point
    _app = IngestAPI()
    app = _app.webserver
