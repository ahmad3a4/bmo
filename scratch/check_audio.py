import subprocess
with open("/home/ahmad/aria/aria_out.txt", "w") as f:
    try:
        r1 = subprocess.run(["amixer", "scontrols"], capture_output=True, text=True)
        f.write("--- amixer scontrols ---\n" + r1.stdout + "\n")
        
        r2 = subprocess.run(["aplay", "-l"], capture_output=True, text=True)
        f.write("--- aplay -l ---\n" + r2.stdout + "\n")
        
        r3 = subprocess.run(["amixer", "-c", "0", "scontrols"], capture_output=True, text=True)
        f.write("--- amixer -c 0 scontrols ---\n" + r3.stdout + "\n")
        
        r4 = subprocess.run(["amixer", "-c", "1", "scontrols"], capture_output=True, text=True)
        f.write("--- amixer -c 1 scontrols ---\n" + r4.stdout + "\n")
        
        r5 = subprocess.run(["amixer", "-c", "2", "scontrols"], capture_output=True, text=True)
        f.write("--- amixer -c 2 scontrols ---\n" + r5.stdout + "\n")
    except Exception as e:
        f.write(str(e))
