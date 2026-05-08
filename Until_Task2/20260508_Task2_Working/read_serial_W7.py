import os
import csv
import time
import serial
import threading
import subprocess
from datetime import datetime

import matplotlib.pyplot as plt


# ============================================================
# USER CONFIGURATION
# ============================================================

COM_PORT = "COM14"
BAUD_RATE = 230400

SAMPLE_RATE = 6400
BYTES_PER_SAMPLE = 2

TEAM_ID = "Team07"

DEFAULT_DISTANCE_CM = 10

SERIAL_TIMEOUT = 0.1
CHUNK_SIZE = 500

MANUAL_TIMEOUT_MARGIN = 5
DISTANCE_IDLE_GAP = 0.75

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

C_FILE = os.path.join(BASE_DIR, "adc_to_wav.c")

# IMPORTANT:
# Use this working executable name instead of adc_to_wav.exe
EXE_FILE = os.path.join(BASE_DIR, "wav_converter_test.exe")


# ============================================================
# SERIAL COMMANDS
# ============================================================

def connect_serial():
    ser = serial.Serial(
        port=COM_PORT,
        baudrate=BAUD_RATE,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=SERIAL_TIMEOUT
    )

    print(f"Connected to: {ser.name}")
    return ser


def send_manual_command(ser, duration_seconds):
    """
    Processing STM expects:
    8 bytes: b"manual  "
    4 bytes: unsigned integer duration, little-endian
    """

    ser.write(b"manual  ")
    ser.flush()

    time.sleep(0.05)

    ser.write(int(duration_seconds).to_bytes(4, byteorder="little", signed=False))
    ser.flush()


def send_distance_command(ser):
    """
    Processing STM expects exactly 8 bytes.
    """

    ser.write(b"distance")
    ser.flush()


def send_idle_command(ser):
    """
    Processing STM expects exactly 8 bytes.
    """

    ser.write(b"idle    ")
    ser.flush()


# ============================================================
# DATA DECODING AND FILE HELPERS
# ============================================================

def decode_adc_samples(raw_bytes):
    """
    Convert raw UART bytes into 12-bit ADC samples.

    Each ADC sample is 2 bytes:
    byte 0 = LSB
    byte 1 = MSB
    """

    samples = []

    for i in range(0, len(raw_bytes) - 1, 2):
        adc_value = raw_bytes[i] | (raw_bytes[i + 1] << 8)

        if 0 <= adc_value <= 4095:
            samples.append(adc_value)

    return samples


def make_base_filename(mode_name, extra_tag=""):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{TEAM_ID}_{SAMPLE_RATE}Hz_{mode_name}"

    if extra_tag:
        filename += f"_{extra_tag}"

    filename += f"_{timestamp}"

    return os.path.join(BASE_DIR, filename)


def save_raw_file(raw_bytes, base_filename):
    raw_path = f"{base_filename}.data"

    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    print(f"Raw data saved: {raw_path}")
    return raw_path


def save_csv(samples, base_filename):
    csv_path = f"{base_filename}.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow(["Sample Rate (Hz)", SAMPLE_RATE])
        writer.writerow(["Sample Index", "Time (s)", "ADC Value"])

        for i, adc_value in enumerate(samples):
            time_value = i / SAMPLE_RATE
            writer.writerow([i, f"{time_value:.6f}", adc_value])

    print(f"CSV saved: {csv_path}")
    return csv_path


def plot_waveform(samples, base_filename, title_suffix=""):
    png_path = f"{base_filename}.png"

    time_axis = [i / SAMPLE_RATE for i in range(len(samples))]

    plt.figure(figsize=(10, 4))
    plt.plot(time_axis, samples, linewidth=0.5)
    plt.title(f"{TEAM_ID} Audio Waveform ({SAMPLE_RATE} Hz) {title_suffix}".strip())
    plt.xlabel("Time (seconds)")
    plt.ylabel("Amplitude (ADC Value)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(png_path, dpi=150)
    plt.close()

    print(f"Waveform plot saved: {png_path}")
    return png_path


# ============================================================
# C WAV CONVERTER
# ============================================================

def ensure_converter_compiled():
    """
    Compile adc_to_wav.c into wav_converter_test.exe.
    """

    if not os.path.exists(C_FILE):
        print(f"ERROR: Missing C file: {C_FILE}")
        return False

    print("Compiling adc_to_wav.c ...")

    compile_result = subprocess.run(
        ["gcc", C_FILE, "-o", EXE_FILE],
        capture_output=True,
        text=True
    )

    if compile_result.returncode != 0:
        print("Compilation failed.")
        print(compile_result.stderr)
        return False

    print("Compilation successful.")
    return True


def generate_wav(raw_path, base_filename):
    """
    Generate WAV file using the external C converter.
    """

    if not ensure_converter_compiled():
        return None

    wav_path = f"{base_filename}.wav"

    print("Running wav_converter_test.exe ...")

    try:
        run_result = subprocess.run(
            [EXE_FILE, raw_path, wav_path, str(SAMPLE_RATE)],
            capture_output=True,
            text=True,
            timeout=15
        )

    except subprocess.TimeoutExpired:
        print("ERROR: wav_converter_test.exe timed out.")
        subprocess.run(
            ["taskkill", "/IM", "wav_converter_test.exe", "/F"],
            capture_output=True,
            text=True
        )
        return None

    if run_result.stdout:
        print(run_result.stdout)

    if run_result.stderr:
        print(run_result.stderr)

    if run_result.returncode != 0:
        print("ERROR: wav_converter_test.exe failed.")
        return None

    if os.path.exists(wav_path):
        print(f"WAV saved: {wav_path}")
        print(f"WAV size: {os.path.getsize(wav_path)} bytes")
        return wav_path

    print("ERROR: WAV file was not generated.")
    return None


# ============================================================
# OUTPUT PIPELINE
# ============================================================

def choose_output_option():
    print("\nChoose output format:")
    print("1. WAV only")
    print("2. PNG only")
    print("3. CSV only")
    print("4. ALL (WAV + PNG + CSV)")

    while True:
        choice = input("Enter option (1-4): ").strip()

        if choice in {"1", "2", "3", "4"}:
            return choice

        print("Invalid option. Please choose 1, 2, 3, or 4.")


def generate_requested_outputs(raw_bytes, mode_name, output_choice, extra_tag=""):
    samples = decode_adc_samples(raw_bytes)

    if len(samples) == 0:
        print("ERROR: No valid ADC samples received.")
        return

    print(f"Valid samples: {len(samples)}")

    base_filename = make_base_filename(mode_name, extra_tag)

    raw_path = save_raw_file(raw_bytes, base_filename)

    if output_choice == "1":
        generate_wav(raw_path, base_filename)

    elif output_choice == "2":
        plot_waveform(samples, base_filename, title_suffix=f"- {mode_name}")

    elif output_choice == "3":
        save_csv(samples, base_filename)

    elif output_choice == "4":
        # CSV and PNG first, so they still generate even if WAV conversion fails.
        save_csv(samples, base_filename)
        plot_waveform(samples, base_filename, title_suffix=f"- {mode_name}")
        generate_wav(raw_path, base_filename)


# ============================================================
# MANUAL RECORDING MODE
# ============================================================

def read_exact_bytes(ser, total_bytes, timeout_seconds):
    raw_data = bytearray()
    start_time = time.time()

    while len(raw_data) < total_bytes:
        remaining = total_bytes - len(raw_data)

        chunk = ser.read(min(CHUNK_SIZE, remaining))

        if chunk:
            raw_data.extend(chunk)
            print(f"Received {len(raw_data)}/{total_bytes} bytes")

        if time.time() - start_time > timeout_seconds:
            print("Timeout: recording stopped early.")
            break

    return bytes(raw_data)


def manual_mode(ser):
    print("\n=== Manual Recording Mode ===")
    print("You will enter a recording duration in seconds.")

    while True:
        duration_str = input("Enter recording duration in seconds: ").strip()

        if duration_str.isdigit() and int(duration_str) > 0:
            duration = int(duration_str)
            break

        print("Please enter a positive whole number.")

    output_choice = choose_output_option()

    total_bytes = SAMPLE_RATE * duration * BYTES_PER_SAMPLE
    timeout_seconds = duration + MANUAL_TIMEOUT_MARGIN

    print("\nManual mode selected.")
    print(f"Duration: {duration} second(s)")
    print(f"Expected bytes: {total_bytes}")

    ser.reset_input_buffer()

    send_manual_command(ser, duration)

    raw_bytes = read_exact_bytes(ser, total_bytes, timeout_seconds)

    send_idle_command(ser)

    print(f"Final bytes received: {len(raw_bytes)}")

    if len(raw_bytes) == 0:
        print("ERROR: No data received.")
        return

    generate_requested_outputs(
        raw_bytes=raw_bytes,
        mode_name="manual",
        output_choice=output_choice,
        extra_tag=f"{duration}s"
    )


# ============================================================
# DISTANCE TRIGGER MODE
# ============================================================

def wait_for_enter(stop_event):
    input()
    stop_event.set()


def capture_distance_event(ser, stop_event):
    """
    Capture one distance-triggered recording event.

    The Processing STM controls when UART data is sent.
    Python treats a burst of received data as one event.
    """

    raw_data = bytearray()

    recording_started = False
    last_data_time = None

    while not stop_event.is_set():
        chunk = ser.read(CHUNK_SIZE)

        if chunk:
            if not recording_started:
                recording_started = True
                print("Trigger detected. Recording started...")

            raw_data.extend(chunk)
            last_data_time = time.time()

        else:
            if recording_started and last_data_time is not None:
                if time.time() - last_data_time > DISTANCE_IDLE_GAP:
                    print("Recording stopped after trigger ended.")
                    break

    return bytes(raw_data)


def distance_mode(ser):
    print("\n=== Distance Trigger Mode ===")
    print("The Processing STM will start/stop recording based on the ultrasonic sensor.")
    print(f"Suggested/default trigger distance: {DEFAULT_DISTANCE_CM} cm")
    print("The CLI will keep listening for repeated trigger events.")
    print("Press ENTER at any time to exit distance mode.")

    output_choice = choose_output_option()

    stop_event = threading.Event()
    stop_thread = threading.Thread(
        target=wait_for_enter,
        args=(stop_event,),
        daemon=True
    )

    ser.reset_input_buffer()
    send_distance_command(ser)

    print("\nDistance trigger mode active.")
    print("Waiting for trigger events...")
    print("Press ENTER to stop this mode.")

    stop_thread.start()

    event_counter = 1

    try:
        while not stop_event.is_set():
            raw_bytes = capture_distance_event(ser, stop_event)

            if raw_bytes:
                print(f"Event {event_counter}: captured {len(raw_bytes)} bytes")

                generate_requested_outputs(
                    raw_bytes=raw_bytes,
                    mode_name="distance",
                    output_choice=output_choice,
                    extra_tag=f"event{event_counter:02d}"
                )

                event_counter += 1

    finally:
        send_idle_command(ser)
        print("Exited distance trigger mode.")


# ============================================================
# MAIN MENU
# ============================================================

def print_main_menu():
    print("\n========================================")
    print(" AUDIO RECORDING SYSTEM CLI")
    print("========================================")
    print("1. Manual Recording Mode")
    print("2. Distance Trigger Mode")
    print("0. Exit")
    print("========================================")


def main():
    ser = connect_serial()

    try:
        while True:
            print_main_menu()

            choice = input("Select an operating mode: ").strip()

            if choice == "1":
                manual_mode(ser)

            elif choice == "2":
                distance_mode(ser)

            elif choice == "0":
                send_idle_command(ser)
                print("Exiting CLI.")
                break

            else:
                print("Invalid option. Please choose 0, 1, or 2.")

    finally:
        try:
            send_idle_command(ser)
        except Exception:
            pass

        if ser.is_open:
            ser.close()

        print("Serial closed.")


if __name__ == "__main__":
    main()