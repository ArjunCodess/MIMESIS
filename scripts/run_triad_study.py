"""Run a feature study from explicit protocol, packet and withheld records."""
import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter
from src.triad_study import Protocol, Packet, FineObservation, freeze, select, evaluate, challenge


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['schema', 'freeze', 'select', 'evaluate', 'challenge'])
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--packets', type=Path)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.stage == 'schema':
        result = {'protocol': Protocol.model_json_schema(), 'packet': Packet.model_json_schema(),
                  'fine_observation': FineObservation.model_json_schema()}
    elif args.stage == 'freeze':
        if not args.protocol or not args.packets:
            parser.error('freeze requires --protocol and --packets')
        protocol = Protocol.model_validate_json(args.protocol.read_text())
        packets = TypeAdapter(list[Packet]).validate_json(args.packets.read_text())
        result = freeze(protocol, packets)
    elif args.stage == 'select':
        if not args.lock:
            parser.error('select requires --lock with an eligible frozen study')
        result = select(json.loads(args.lock.read_text()))
    else:
        if not args.lock or not args.observations:
            parser.error('evaluate requires --lock and --observations')
        selection = json.loads(args.lock.read_text())
        if args.stage == 'challenge':
            variants = TypeAdapter(dict[str, list[FineObservation]]).validate_json(args.observations.read_text())
            result = challenge(selection, variants)
        else:
            observations = TypeAdapter(list[FineObservation]).validate_json(args.observations.read_text())
            result = evaluate(selection, observations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(args.stage, result.get('state', result.get('claim', 'schema exported')))
    if result.get('state') == 'not_ready':
        for failure in result['failures']:
            print('-', failure)


if __name__ == '__main__':
    main()
