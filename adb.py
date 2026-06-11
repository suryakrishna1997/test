import subprocess
import time
import json
import os

RECORD_FILE = "recorded_steps.json"
ITERATIONS = 100

# ── RECORDER ──────────────────────────────────────────
def record_steps():
    steps = []
    print("\n=== RECORD MODE ===")
    print("Commands: tap | swipe | wait | done")
    
    while True:
        cmd = input("\nAction: ").strip().lower()
        
        if cmd == "tap":
            # Take screenshot and show current screen
            subprocess.run("adb shell screencap -p /sdcard/screen.png", shell=True)
            subprocess.run("adb pull /sdcard/screen.png screen.png", shell=True)
            
            x = int(input("  X coordinate: "))
            y = int(input("  Y coordinate: "))
            label = input("  Label (e.g. 'tap_bluetooth'): ")
            
            steps.append({"action": "tap", "x": x, "y": y, "label": label})
            print(f"  ✔ Recorded tap at ({x}, {y})")

        elif cmd == "swipe":
            x1 = int(input("  Start X: "))
            y1 = int(input("  Start Y: "))
            x2 = int(input("  End X: "))
            y2 = int(input("  End Y: "))
            duration = int(input("  Duration ms (e.g. 300): "))
            label = input("  Label: ")
            
            steps.append({
                "action": "swipe",
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "duration": duration,
                "label": label
            })
            print(f"  ✔ Recorded swipe ({x1},{y1}) → ({x2},{y2})")

        elif cmd == "wait":
            ms = int(input("  Wait duration ms: "))
            steps.append({"action": "wait", "ms": ms})
            print(f"  ✔ Recorded wait {ms}ms")

        elif cmd == "done":
            break
        else:
            print("  Unknown command.")

    with open(RECORD_FILE, "w") as f:
        json.dump(steps, f, indent=2)
    
    print(f"\n✅ Saved {len(steps)} steps to {RECORD_FILE}")
    return steps


# ── PLAYER ────────────────────────────────────────────
def play_steps(steps, iterations):
    print(f"\n=== REPLAY MODE — {iterations} iterations ===\n")
    
    results = []

    for i in range(1, iterations + 1):
        print(f"── Iteration {i}/{iterations} ──")
        iteration_passed = True

        for step in steps:
            action = step["action"]

            if action == "tap":
                subprocess.run(
                    f"adb shell input tap {step['x']} {step['y']}",
                    shell=True
                )
                print(f"  ✔ tap ({step['x']}, {step['y']}) — {step.get('label','')}")

            elif action == "swipe":
                subprocess.run(
                    f"adb shell input swipe {step['x1']} {step['y1']} "
                    f"{step['x2']} {step['y2']} {step['duration']}",
                    shell=True
                )
                print(f"  ✔ swipe — {step.get('label','')}")

            elif action == "wait":
                time.sleep(step["ms"] / 1000)
                print(f"  ✔ wait {step['ms']}ms")

            time.sleep(0.3)  # small gap between steps

        # capture logcat snapshot per iteration for crash detection
        log = subprocess.run(
            "adb shell logcat -d -t 50 *:E",
            shell=True, capture_output=True, text=True
        ).stdout

        crashed = any(k in log for k in ["FATAL EXCEPTION", "ANR in", "crash"])
        status = "FAIL ❌" if crashed else "PASS ✅"
        results.append({"iteration": i, "status": status})
        print(f"  → {status}\n")

        if crashed:
            # save crash log
            with open(f"crash_iter_{i}.log", "w") as f:
                f.write(log)
            print(f"  ⚠ Crash log saved: crash_iter_{i}.log")

    # ── SUMMARY ──
    passed = sum(1 for r in results if "PASS" in r["status"])
    failed = iterations - passed
    print("=" * 40)
    print(f"SUMMARY: {passed} PASS / {failed} FAIL out of {iterations}")
    print("=" * 40)

    with open("replay_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results saved to replay_results.json")


# ── MAIN ──────────────────────────────────────────────
def main():
    print("AOSP IVI Reproduction Tool")
    print("-" * 30)

    if os.path.exists(RECORD_FILE):
        choice = input(f"'{RECORD_FILE}' found. (R)ecord new / (P)lay existing? ").strip().upper()
    else:
        choice = "R"

    if choice == "R":
        steps = record_steps()
    else:
        with open(RECORD_FILE) as f:
            steps = json.load(f)
        print(f"Loaded {len(steps)} steps from {RECORD_FILE}")

    n = input(f"\nHow many iterations? (default {ITERATIONS}): ").strip()
    iterations = int(n) if n.isdigit() else ITERATIONS

    play_steps(steps, iterations)


if __name__ == "__main__":
    main()