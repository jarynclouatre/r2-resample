#!/usr/bin/env python3
import subprocess, os, json, logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/workspace/resample.log'),
        logging.StreamHandler()
    ]
)

BUCKET = 'dinkeyes-music'
REMOTE = 'r2music'
WORK_DIR = '/tmp/resample_work'
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'
FOLDER_PREFIX = os.environ.get('FOLDER_PREFIX', '')
os.makedirs(WORK_DIR, exist_ok=True)

def build_rclone_config():
    os.makedirs(os.path.expanduser('~/.config/rclone'), exist_ok=True)
    with open(os.path.expanduser('~/.config/rclone/rclone.conf'), 'w') as f:
        f.write(f"""[r2music]
type = s3
provider = Cloudflare
access_key_id = {os.environ['R2_ACCESS_KEY']}
secret_access_key = {os.environ['R2_SECRET_KEY']}
endpoint = https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com
acl = private
""")

def list_flacs():
    target = f'{REMOTE}:{BUCKET}/{FOLDER_PREFIX}' if FOLDER_PREFIX else f'{REMOTE}:{BUCKET}'
    result = subprocess.run(
        ['rclone', 'lsjson', '--recursive', target, '--include', '*.flac'],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)

def get_sample_rate(filepath):
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', filepath],
        capture_output=True, text=True, check=True
    )
    for stream in json.loads(result.stdout).get('streams', []):
        if stream.get('codec_type') == 'audio':
            return int(stream.get('sample_rate', 0))
    return 0

def target_rate(sample_rate):
    if sample_rate in (176400, 352800):
        return 88200
    if sample_rate in (192000, 384000):
        return 96000
    return None

def main():
    build_rclone_config()
    if DRY_RUN:
        logging.info("=== DRY RUN MODE - no files will be modified ===")
    if FOLDER_PREFIX:
        logging.info(f"Scoping to folder: {FOLDER_PREFIX}")
    logging.info("Listing FLACs...")
    files = list_flacs()
    logging.info(f"Found {len(files)} FLAC files")
    processed = skipped = errors = 0

    for f in files:
        remote_path = f'{FOLDER_PREFIX}/{f["Path"]}' if FOLDER_PREFIX else f['Path']
        local_input = os.path.join(WORK_DIR, 'input.flac')
        local_output = os.path.join(WORK_DIR, 'output.flac')
        try:
            subprocess.run([
                'rclone', 'copyto',
                f'{REMOTE}:{BUCKET}/{remote_path}',
                local_input
            ], check=True, capture_output=True)

            sample_rate = get_sample_rate(local_input)
            rate = target_rate(sample_rate)
            os.remove(local_input)

            if rate is None:
                logging.info(f"SKIP {remote_path} ({sample_rate}Hz)")
                skipped += 1
                continue

            if DRY_RUN:
                logging.info(f"WOULD RESAMPLE {remote_path} ({sample_rate}Hz -> {rate}Hz)")
                processed += 1
                continue

            logging.info(f"RESAMPLE {remote_path} ({sample_rate}Hz -> {rate}Hz)")
            subprocess.run([
                'rclone', 'copyto',
                f'{REMOTE}:{BUCKET}/{remote_path}',
                local_input
            ], check=True, capture_output=True)

            subprocess.run([
                'sox', local_input, '-b', '24', local_output,
                'rate', '-v', '-s', str(rate)
            ], check=True)

            if get_sample_rate(local_output) != rate:
                raise ValueError("Output rate mismatch")

            subprocess.run([
                'rclone', 'copyto', local_output,
                f'{REMOTE}:{BUCKET}/{remote_path}'
            ], check=True, capture_output=True)

            processed += 1
        except Exception as e:
            logging.error(f"ERROR {remote_path}: {e}")
            errors += 1
        finally:
            for p in [local_input, local_output]:
                if os.path.exists(p):
                    os.remove(p)

    if DRY_RUN:
        logging.info(f"Dry run complete. Would resample: {processed}, Would skip: {skipped}, Errors: {errors}")
    else:
        logging.info(f"Done. Processed: {processed}, Skipped: {skipped}, Errors: {errors}")

if __name__ == '__main__':
    main()
