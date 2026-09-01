import sounddevice as sd
import numpy as np
import time

def test_mic(duration=5, device=None):
    print(f"Testing microphone for {duration} seconds...")
    print(f"Using device: {device if device is not None else 'default'}")
    
    samples = []
    
    def callback(indata, frames, time, status):
        if status:
            print(f"Error: {status}")
        vol = np.linalg.norm(indata) / np.sqrt(len(indata))
        samples.append(vol)
        # Visual feedback
        bars = int(vol * 100)
        print(f"\rVolume: [{'#' * bars}{' ' * (50 - bars)}] {vol:.4f}", end="")

    try:
        with sd.InputStream(device=device, channels=1, callback=callback):
            time.sleep(duration)
        print("\nTest complete.")
        if samples:
            print(f"Max volume detected: {max(samples):.4f}")
            print(f"Average volume: {np.mean(samples):.4f}")
            print(f"Min volume: {min(samples):.4f}")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    # Load config to get the device
    import json
    import os
    
    cfg_path = "/home/ahmad/aria/config.json"
    device_name = None
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = json.load(f)
            device_name = cfg.get("input_device")
            print(f"Configured device: {device_name}")

    def resolve_device(name):
        if not name: return None
        devs = sd.query_devices()
        for i, d in enumerate(devs):
            if d.get("max_input_channels", 0) > 0 and name.lower() in d.get("name", "").lower():
                return i
        return None

    dev_idx = resolve_device(device_name)
    test_mic(device=dev_idx)
