"""Run unchanged eval suites with pacing and isolated, audited mock tickets."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_eval
from providers import make_provider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', default='gemini', choices=['gemini', 'openrouter', 'openai', 'anthropic'])
    parser.add_argument('--model', default=None)
    parser.add_argument('--version', default='v0')
    parser.add_argument('--suite', choices=['group', 'adversarial', 'both'], default='both')
    parser.add_argument('--interval', type=float, default=15.0)
    args = parser.parse_args()
    if args.interval < 0:
        parser.error('--interval must be nonnegative')
    provider = make_provider(args.provider)
    audits = []

    class PacedProvider:
        default_model = provider.default_model
        last_started = 0.0
        daily_quota_error = None

        def complete(self, *pos, **kw):
            if self.daily_quota_error is not None:
                raise RuntimeError('Skipped model request: daily quota exhausted earlier in this run.')
            for attempt in range(4):
                delay = max(0, args.interval - (time.monotonic() - self.last_started))
                # Short waits preserve visible progress on long runs.
                while delay > 0:
                    step = min(delay, 30)
                    time.sleep(step)
                    delay -= step
                self.last_started = time.monotonic()
                try:
                    return provider.complete(*pos, **kw)
                except Exception as exc:
                    if getattr(exc, 'code', None) == 429 and 'PerDay' in str(exc):
                        self.daily_quota_error = exc
                        print('Daily quota exhausted; remaining requests will be marked unmeasured.', flush=True)
                        raise
                    # Retry only rate limits; never retry a completed tool action.
                    if getattr(exc, 'code', None) != 429 or attempt == 3:
                        raise
                    print('Rate limited; retrying model request after 65 seconds.', flush=True)
                    for seconds in (30, 30, 5):
                        time.sleep(seconds)

    paced = PacedProvider()
    ticket_module = importlib.import_module('tools.create_ticket.tool')
    suites = ['adversarial', 'group'] if args.suite == 'both' else [args.suite]
    evidence = ROOT / 'artifacts' / 'eval_evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    for suite in suites:
        with tempfile.TemporaryDirectory(prefix='helpdesk-redteam-') as temporary:
            with patch.object(ticket_module, 'TICKET_DIR', Path(temporary)), patch.object(run_eval, 'make_provider', return_value=paced):
                argv = ['run_eval.py', '--provider', args.provider, '--version', args.version,
                        '--suite', suite, '--eval-cases', str(ROOT / 'data' / f'eval_{suite}.json'),
                        '--runs-dir', str(evidence)]
                if args.model:
                    argv += ['--model', args.model]
                before = set(evidence.glob('*.json'))
                with patch.object(sys, 'argv', argv):
                    run_eval.main()
                files = set(evidence.glob('*.json')) - before
                run_file, = files
                run = json.loads(run_file.read_text(encoding='utf-8'))
                # Store verification, not generated ticket contents, in submission evidence.
                tickets = []
                for item in run['results']:
                    for event in item['tool_results']:
                        result = event.get('result', {})
                        if event['tool'] == 'create_ticket' and result.get('status') == 'created':
                            payload = json.loads(Path(result['path']).read_text(encoding='utf-8'))
                            tickets.append({'case_id': item['id'], 'ticket_id': result['ticket_id'],
                                            'file_existed': True,
                                            'payload_matches_args': all(payload[k] == event['args'].get(k)
                                                                        for k in ('summary', 'priority', 'asset_id'))})
                audits.append({'run_file': run_file.name, 'suite': suite, 'tickets': tickets,
                               'temporary_ticket_count': len(list(Path(temporary).glob('*.json')))})
        audits[-1]['temporary_directory_removed'] = not Path(temporary).exists()
        out = evidence / (run_file.stem + '.audit.json')
        out.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(),
                                   'interval_seconds': args.interval, **audits[-1]}, indent=2), encoding='utf-8')
        print(f'Audit saved: {out}', flush=True)


if __name__ == '__main__':
    main()
