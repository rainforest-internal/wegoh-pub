"""Export one completed KST day of WegoH API observations to a protected JSONL file."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from api_quality_metrics import analysis_record, decode_journal_message


UNIT = 'wegoh-live-api.service'
SEOUL = ZoneInfo('Asia/Seoul')
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DAY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_JOURNAL_MICROSECONDS = re.compile(r'[0-9]{1,18}')


class ArchiveError(Exception):
    pass


def archive_day(value, now):
    today = now.astimezone(SEOUL).date()
    if value == 'previous':
        return today - timedelta(days=1)
    if not _DAY.fullmatch(value):
        raise ArchiveError('Date must be YYYY-MM-DD or previous.')
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ArchiveError('Date is not a calendar day.') from None
    if day >= today:
        raise ArchiveError('Only completed KST days can be archived.')
    if day <= EPOCH.date():
        raise ArchiveError('Date must be after the journal epoch.')
    return day


def _window(day):
    return tuple(datetime.combine(value, time.min, SEOUL).astimezone(timezone.utc)
                 for value in (day, day + timedelta(days=1)))


def _observation(line, start, end):
    if len(line) > 8192:
        return None
    try:
        entry = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if type(entry) is not dict or entry.get('_SYSTEMD_UNIT') != UNIT:
        return None
    timestamp = entry.get('__REALTIME_TIMESTAMP')
    message = entry.get('MESSAGE')
    if type(message) is not str or type(timestamp) is not str or not _JOURNAL_MICROSECONDS.fullmatch(timestamp):
        return None
    try:
        received = EPOCH + timedelta(microseconds=int(timestamp))
    except OverflowError:
        return None
    if not start <= received < end:
        return None
    observed_at = received.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    return analysis_record(decode_journal_message(message), observed_at)


@contextmanager
def _journal(start, end):
    def timestamp(value):
        return value.strftime('%Y-%m-%d %H:%M:%S UTC')

    command = ['/usr/bin/journalctl', '--no-pager', '--output=json',
               '--output-fields=MESSAGE,_SYSTEMD_UNIT', '--since=' + timestamp(start),
               '--until=' + timestamp(end), '_SYSTEMD_UNIT=' + UNIT]
    with tempfile.TemporaryFile() as errors:
        try:
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                     text=True, encoding='utf-8', errors='replace')
        except OSError:
            raise ArchiveError('Cannot start journalctl.') from None
        try:
            with child.stdout:
                yield child.stdout
            status = child.wait()
            # Do not copy diagnostics into metrics. Journalctl may return zero
            # while warning that the selected caller cannot read system entries.
            if status or errors.tell():
                raise ArchiveError('Journal read failed or reported warnings. Check journal permissions and availability.')
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def _existing(target):
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or not info.st_size):
        raise ArchiveError('Existing archive is not a protected regular file owned by this account.')
    return True


def export(day, output_dir, source=_journal):
    directory = output_dir.resolve(strict=True)
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ArchiveError('Output directory must be owned by this account with mode 0700.')
    name = f'api-quality-{day.isoformat()}.jsonl'
    target = directory / name
    if _existing(target):
        return dict(status='already_present', date=day.isoformat(), file=name)

    start, end = _window(day)
    count = 0
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                     dir=directory, prefix='.api-quality-') as output:
        with source(start, end) as lines:
            for line in lines:
                observation = _observation(line, start, end)
                if observation is not None:
                    output.write(json.dumps(observation, separators=(',', ':')) + '\n')
                    count += 1
        if not count:
            return dict(status='no_observations', date=day.isoformat(), records=0)
        output.flush()
        os.fsync(output.fileno())
        try:
            os.link(output.name, target)
        except FileExistsError:
            if _existing(target):
                return dict(status='already_present', date=day.isoformat(), file=name)
            raise ArchiveError('Archive changed while publishing.') from None
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return dict(status='archived', date=day.isoformat(), records=count, file=name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default='previous', help='KST date, YYYY-MM-DD or previous')
    parser.add_argument('--output-dir', type=Path, default=Path('/var/lib/wegoh-api-quality'),
                        help='Existing private archive directory')
    options = parser.parse_args()
    try:
        day = archive_day(options.date, datetime.now(timezone.utc))
        result = export(day, options.output_dir)
    except ArchiveError as error:
        print(f'API quality archive: {error}', file=sys.stderr)
        return 1
    except OSError:
        print('API quality archive: cannot read or write the archive.', file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
