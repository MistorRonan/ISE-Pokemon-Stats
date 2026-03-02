import sys
import json
from sqlalchemy import create_engine, func
import PCInfo
import PokemonInfo
from sqlalchemy.orm import Session
import logging
from lib_config.config import Config
from lib_utils.blocktimer import BlockTimer
from datetime import datetime, timezone
from lib_metrics_datamodel.metrics_datamodel import DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
from flask import Flask, request
from models import *

class Application:
    def __init__(self):
        """Initialize the application with required configuration and logging."""
        self.config = Config(__file__)
        self.logger = logging.getLogger(__name__)
        self.webserver = Flask(__name__)
        self.setup_routes()
        self.engine = create_engine(self.config.database.connection_string)
        self.logger.debug("Application initialized")


    def setup_routes(self):
        """Setup the routes for the application."""
        self.webserver.route("/hello")(self.hello_world)
        self.webserver.route("/aggregator_snapshots", methods=['POST'])(self.upload_snapshot)
        self.webserver.route("/aggregators", methods=['GET', 'POST'])(self.handle_aggregators)
        self.webserver.route("/devices", methods=['GET', 'POST'])(self.handle_devices)
        self.webserver.route("/metrics", methods=['GET'])(self.get_metrics)
        self.webserver.route("/pc_info", methods=['GET'])(self.get_pc_info)
        self.webserver.route("/pokemon_info", methods=['GET'])(self.get_pokemon_info)

    def hello_world(self):
        """Hello world route."""
        self.logger.info("Hello world route called")
        return {'message': 'Hello, World from the Data Reading Web Server! Use /aggregator_snapshots to upload data.'}

    def upload_snapshot(self):
        """Upload aggregator snapshot route.
        Expects a JSON representation of the DTO_Aggregator object.
        """
        session = None
        try:
            self.logger.info("About to deserialize the incoming JSON to DTO_Aggregator")
            # Deserialize the incoming JSON to DTO_Aggregator
            data = request.get_json()
            dto_aggregator = DTO_Aggregator.from_dict(data) 
        
            self.logger.info("JSON Deserialized. Storing aggregator snapshot: %s", dto_aggregator)

            session = Session(self.engine)
            
            # Find or create aggregator
            aggregator = session.query(Aggregator).filter_by(guid=str(dto_aggregator.guid)).first()
            if not aggregator:
                aggregator = Aggregator(
                    guid=str(dto_aggregator.guid),
                    name=dto_aggregator.name
                )
                session.add(aggregator)
                session.flush()  # Get the ID

            # Process each device
            for dto_device in dto_aggregator.devices:
                # Find or create device
                device = session.query(Device).filter_by(
                    aggregator_id=aggregator.aggregator_id,
                    name=dto_device.name
                ).first()
                
                if not device:
                    # Get max ordinal for this aggregator
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

                # Create snapshots
                now_UTC = datetime.now(timezone.utc)
                for dto_snapshot in dto_device.data_snapshots:
                    snapshot = MetricSnapshot(
                        device_id=device.device_id,
                        client_utc_timestamp_epoch=int(dto_snapshot.timestamp_utc.timestamp()),
                        client_timezone_mins=dto_snapshot.timezone_mins,
                        server_utc_timestamp_epoch=int(now_UTC.timestamp()),
                        server_timezone_mins=int(now_UTC.astimezone().utcoffset().total_seconds() / 60)
                    )
                    session.add(snapshot)
                    session.flush()

                    # Process metrics
                    for dto_metric in dto_snapshot.metrics:
                        # Find or create metric type
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

                        # Create metric value
                        metric_value = MetricValue(
                            metric_snapshot_id=snapshot.metric_snapshot_id,
                            device_metric_type_id=metric_type.device_metric_type_id,
                            value=float(dto_metric.value)
                        )
                        session.add(metric_value)

            session.commit()
            session.close()
            # Placeholder for writing to the database
            # db.save(dto_aggregator)  # Uncomment and implement as needed
            
            return {
                'status': 'success',
                'message': 'Aggregator snapshot uploaded successfully'
            }, 201
            
        except Exception as e:
            if session is not None:
                self.logger.error("Rolling back session due to error: %s", str(e))
                try:    
                    session.rollback()
                    session.close()
                except Exception as e:
                    self.logger.exception("Error rolling back session: %s", str(e))
                    
            self.logger.exception("Error in upload_snapshot route: %s", str(e))
            return {
                'status': 'error',
                'message': str(e)
            }, 500

    def handle_aggregators(self):
        """Handle GET and POST requests for aggregators."""
        if request.method == 'GET':
            return self.get_aggregator()
        elif request.method == 'POST':
            return self.create_aggregator()

    def get_aggregator(self):
        """Get an existing aggregator by GUID or get all aggregators."""
        guid = request.args.get('guid')
        session = Session(self.engine)
        aggregators = []
        try:
            if guid:
                # Get single aggregator
                aggregator = session.query(Aggregator).filter_by(guid=guid).first()
                if not aggregator:
                    return {'status': 'error', 'message': f'No aggregator found with GUID {guid}'}, 404
                aggregators = [aggregator]
            else:
                # Get all aggregators
                aggregators = session.query(Aggregator).all()
            
        finally:
            session.close()

        # Convert aggregators to DTO objects
        dto_aggregators = []
        for aggregator in aggregators:
            dto_aggregator = DTO_Aggregator(
                guid=aggregator.guid,
                name=aggregator.name,
                devices=[]
            )
            dto_aggregators.append(dto_aggregator.to_dict())
        return {'status': 'success', 'aggregators': dto_aggregators}, 200

    def create_aggregator(self):
        """Create a new aggregator."""
        data = request.get_json()
        if 'guid' not in data or 'name' not in data:
            return {'status': 'error', 'message': 'GUID and name are required'}, 400
        
        guid = data['guid']
        session = Session(self.engine)
        existing_aggregator = session.query(Aggregator).filter_by(guid=guid).first()
        
        if existing_aggregator:
            session.close()
            return {'status': 'error', 'message': 'Aggregator with this GUID already exists'}, 400
        
        new_aggregator = Aggregator(guid=guid, name=data['name'])
        session.add(new_aggregator)
        session.commit()
        # capture the ID of the new aggregator before the session is closed
        new_aggregator_id = new_aggregator.aggregator_id
        session.close()
        
        return {'status': 'success', 'aggregator_id': new_aggregator_id}, 201

    def handle_devices(self):
        """Handle GET and POST requests for devices."""
        if request.method == 'GET':
            return self.get_device()
        elif request.method == 'POST':
            return self.create_device()

    def get_device(self):
        """Get an existing device by name and aggregator ID."""
        aggregator_guid = request.args.get('aggregator_guid')
        if not aggregator_guid:
            return {'status': 'error', 'message': 'Aggregator GUID is required'}, 400
            
        name = request.args.get('name')
        session = Session(self.engine)
        devices = []
        try:
            if name:
                # Get single device
                device = session.query(Device).join(Aggregator).filter(
                    Aggregator.guid == aggregator_guid,
                    Device.name == name
                ).first()
                if not device:
                    return {'status': 'error', 'message': f'No device found with name {name} for aggregator {aggregator_guid}'}, 404
                devices = [device]
            else:
                # Get all devices for this aggregator
                devices = session.query(Device).join(Aggregator).filter(
                    Aggregator.guid == aggregator_guid,
                ).all()
        finally:
            session.close()

        # Convert devices to DTOs for response
        device_dtos = []
        for device in devices:
            device_dto = DTO_Device(
                name=device.name,
                data_snapshots=[]
            )
            device_dtos.append(device_dto)
        return {'status': 'success', 'devices': device_dtos}, 200

    def create_device(self):
        """Create a new device."""
        data = request.get_json()
        if 'aggregator_guid' not in data or 'name' not in data:
            return {'status': 'error', 'message': 'Aggregator ID and device name are required'}, 400
        
        aggregator_guid = data['aggregator_guid']
        name = data['name']
        session = Session(self.engine)
        
        # First get the aggregator to link to
        aggregator = session.query(Aggregator).filter_by(guid=aggregator_guid).first()
        if not aggregator:
            session.close()
            return {'status': 'error', 'message': 'Aggregator not found'}, 404

        # Check if the device already exists for the given aggregator
        existing_device = session.query(Device).filter_by(
            aggregator_id=aggregator.aggregator_id,
            name=name
        ).first()
        
        if existing_device:
            session.close()
            return {'status': 'error', 'message': 'Device with this name already exists for the given aggregator'}, 400
        
        # Get the maximum ordinal for this aggregator's devices
        max_ordinal = session.query(func.max(Device.ordinal)).filter_by(aggregator_id=aggregator.aggregator_id).scalar()
        # Set ordinal to 0 if first device, otherwise max + 1
        ordinal = 0 if max_ordinal is None else max_ordinal + 1
        
        # Create device linked to aggregator via aggregator_id
        new_device = Device(
            aggregator_id=aggregator.aggregator_id,
            name=name, 
            ordinal=ordinal
        )
        session.add(new_device)
        session.commit()    
        # capture the ID of the new device before the session is closed
        new_device_id = new_device.device_id
        session.close()
        
        return {'status': 'success', 'device_id': new_device_id}, 201

    def get_metrics(self):
        """Get metric values based on optional parameters."""
        session = Session(self.engine)
        try:
            guid = request.args.get('guid')
            device_name = request.args.get('device_name')
            utc_date_min = datetime.strptime(request.args.get('utc_date_min'), '%Y-%m-%d %H:%M:%S') if request.args.get('utc_date_min') else None
            utc_date_max = datetime.strptime(request.args.get('utc_date_max'), '%Y-%m-%d %H:%M:%S') if request.args.get('utc_date_max') else None

            # Start the query from MetricValue and join with MetricSnapshot and Device
            query = session.query(MetricValue).\
                select_from(MetricValue).\
                join(MetricSnapshot, MetricValue.metric_snapshot_id == MetricSnapshot.metric_snapshot_id).\
                join(Device, MetricSnapshot.device_id == Device.device_id). \
                join(Aggregator, Device.aggregator_id == Aggregator.aggregator_id)    

            # Apply filters based on optional parameters
            if guid:
                query = query.filter(Aggregator.guid == guid)
            if device_name:
                query = query.filter(Device.name == device_name)
            if utc_date_min:
                query = query.filter(MetricSnapshot.client_utc_timestamp_epoch >= int(utc_date_min.timestamp()))
            if utc_date_max:
                query = query.filter(MetricSnapshot.client_utc_timestamp_epoch <= int(utc_date_max.timestamp()))

            metric_values = query.all()

            # Build the DTO hierarchy
            aggregator_dtos = {}
            for metric_value in metric_values:
                device = session.query(Device).filter_by(device_id=metric_value.device_metric_type.device_id).first()
                aggregator = session.query(Aggregator).filter_by(aggregator_id=device.aggregator_id).first()

                aggregator_dto = aggregator_dtos.get(aggregator.guid)
                if not aggregator_dto:
                    aggregator_dto = DTO_Aggregator(
                        guid=aggregator.guid,
                        name=aggregator.name,
                        devices=[]
                    )
                    aggregator_dtos[aggregator.guid] = aggregator_dto

                device_dto = next((d for d in aggregator_dto.devices if d.name == device.name), None)
                if not device_dto:
                    device_dto = DTO_Device(
                        name=device.name,
                        data_snapshots=[]
                    )
                    aggregator_dto.devices.append(device_dto)
    
                # Find or create a new DataSnapshot for this metric's timestamp
                data_snapshot = next(
                    (ds for ds in device_dto.data_snapshots 
                     if ds.timestamp_utc == datetime.fromtimestamp(metric_value.metric_snapshot.client_utc_timestamp_epoch)
                     and ds.timezone_mins == metric_value.metric_snapshot.client_timezone_mins),
                    None
                )
                
                if not data_snapshot:
                    data_snapshot = DTO_DataSnapshot(
                        timestamp_utc=datetime.fromtimestamp(metric_value.metric_snapshot.client_utc_timestamp_epoch),
                        timezone_mins=metric_value.metric_snapshot.client_timezone_mins,
                        metrics=[]
                    )
                    device_dto.data_snapshots.append(data_snapshot)

                metric_dto = DTO_Metric(
                    name=metric_value.device_metric_type.name,
                    value=metric_value.value,
                )
                data_snapshot.metrics.append(metric_dto)

            return {'status': 'success', 'aggregators': list(aggregator_dtos.values())}, 200

        except Exception as e:
            self.logger.exception("Error in get_metrics route: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500
        finally:
            session.close()

    def get_pc_info(self):
        """Return live PC usage stats collected by PCInfo.
        
        GET /pc_info
        
        Returns a flat JSON map with keys such as:
            cpu-usage, cpu-cores,
            memory-usage, memory-used-gb, memory-total-gb, memory-available-gb,
            disk-usage, disk-free-gb, disk-total-gb
        """
        try:
            self.logger.info("pc_info route called")
            data = PCInfo.collect()
            return {'status': 'success', 'data': data}, 200
        except Exception as e:
            self.logger.exception("Error in pc_info route: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500

    def get_pokemon_info(self):
        """Return Pokémon usage/move counts scraped from Pokémon Showdown replays.

        GET /pokemon_info?format=gen9ou&type=mons
        
        Query parameters:
            format  - Showdown format string (default: gen9ou)
                      e.g. gen9ou, gen8randombattle, gen4ou …
            type    - "mons"  → count Pokémon appearances (default)
                      "move"  → count move usage instead

        Returns a JSON object mapping Pokémon/move names to occurrence counts,
        sorted from most to least common.
        """
        try:
            fmt  = request.args.get('format', 'gen9ou')
            kind = request.args.get('type', 'mons')
            param = f"{fmt}|{kind}"
            self.logger.info("pokemon_info route called with param=%s", param)
            data = PokemonInfo.collect(param)
            if data is None:
                return {'status': 'error', 'message': 'No replay data returned for the requested format'}, 404
            return {'status': 'success', 'format': fmt, 'type': kind, 'data': data}, 200
        except Exception as e:
            self.logger.exception("Error in pokemon_info route: %s", str(e))
            return {'status': 'error', 'message': str(e)}, 500

    def run(self) -> int:
        """
        Main application logic.
        Returns:
            int: Exit code (0 for success, non-zero for error)
        """
        try:
            self.logger.info("Starting Flask web server on port %s", self.config.web.port)
            self.webserver.run(debug=self.config.web.debug, port=self.config.web.port)
            self.logger.info("Application completed successfully")
            return 0
            
        except Exception as e:
            self.logger.exception("Application failed with error: %s", str(e))
            return 1
        

def main() -> int:
    """Entry point for the application."""
    app = Application()
    return app.run()

if __name__ == "__main__":
    sys.exit(main())
else:
    """
    If this isn't the main entry point, assume we're hosted on a WSGI
    Web Server and hence create the app object pointing to our Flask
    instance so that the calling WSGI config file has what it needs.
    """
    appForWSGI = Application()
    app = appForWSGI.webserver