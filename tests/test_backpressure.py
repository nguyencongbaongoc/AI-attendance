from app.output.publisher import create_event_bus, BackpressurePolicy, SubscriberConfig, FunctionSubscriber
from app.output.contract import ImmediateEvent, ImmediateEventType, ImmediateEventDirection, IdentityCertainty, EventDeliveryStatus
import sys

bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_OLDEST)
subscriber = FunctionSubscriber('slow_sub', lambda e: None)
bus.subscribe(subscriber, SubscriberConfig(subscriber_id='slow_sub', queue_size=2, backpressure_policy=BackpressurePolicy.DROP_OLDEST))

with bus._subscriber_lock:
    state = bus._subscribers['slow_sub']

event1 = ImmediateEvent(event_id='IEV-test001', event_type=ImmediateEventType.ATTENDANCE_IN, direction=ImmediateEventDirection.IN, identity_certainty=IdentityCertainty.KNOWN, identity_candidate='HS001', identity_confidence=0.987, identity_evidence_ref='GO-001', event_timestamp=1700000000.0, event_frame_index=0, camera_id='CAM1', local_track_id='A17', global_observation_id='GO-001', source_raw_event_id='RIE-001', source_resolution_id='RES-001', geometry_version=1, geometry_config_hash='geom_hash_001', resolver_version='1.0', resolver_config_hash='resolver_hash_001', delivery_status=EventDeliveryStatus.NEW, delivery_sequence=1)
event2 = ImmediateEvent(event_id='IEV-test002', event_type=ImmediateEventType.ATTENDANCE_IN, direction=ImmediateEventDirection.IN, identity_certainty=IdentityCertainty.KNOWN, identity_candidate='HS001', identity_confidence=0.987, identity_evidence_ref='GO-001', event_timestamp=1700000001.0, event_frame_index=30, camera_id='CAM1', local_track_id='A17', global_observation_id='GO-001', source_raw_event_id='RIE-002', source_resolution_id='RES-002', geometry_version=1, geometry_config_hash='geom_hash_001', resolver_version='1.0', resolver_config_hash='resolver_hash_001', delivery_status=EventDeliveryStatus.NEW, delivery_sequence=2)

with state.lock:
    state.queue.append(event1)
    state.queue.append(event2)
    print('Queue before:', [e.event_id for e in state.queue], file=sys.stderr)

event3 = ImmediateEvent(event_id='IEV-test003', event_type=ImmediateEventType.ATTENDANCE_IN, direction=ImmediateEventDirection.IN, identity_certainty=IdentityCertainty.KNOWN, identity_candidate='HS001', identity_confidence=0.987, identity_evidence_ref='GO-001', event_timestamp=1700000002.0, event_frame_index=60, camera_id='CAM1', local_track_id='A17', global_observation_id='GO-001', source_raw_event_id='RIE-003', source_resolution_id='RES-003', geometry_version=1, geometry_config_hash='geom_hash_001', resolver_version='1.0', resolver_config_hash='resolver_hash_001', delivery_status=EventDeliveryStatus.NEW, delivery_sequence=3)

print('Calling publish...', file=sys.stderr)
result = bus.publish(event3)
print(f'Publish returned: {result}', file=sys.stderr)

with state.lock:
    print('Queue after:', [e.event_id for e in state.queue], file=sys.stderr)
    print('Events dropped:', state.events_dropped, file=sys.stderr)