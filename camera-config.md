When configuring a Raspberry Pi Camera Module 3 (IMX708 sensor) on a Raspberry Pi 4 over SSH, the most critical factor is bypassing the graphical user interface.
Because you are using a headless SSH connection, standard camera commands will crash or hang trying to open a desktop preview window. You must use specific flags to disable the preview. [1] 
Note: Depending on your exact Raspberry Pi OS version (Bookworm vs. older Bullseye), commands begin with either rpicam- (newer) or libcamera- (older). Both syntaxes are covered below. [1, 2] 
------------------------------
## 1. Verify the Connection
Run the following command to check if the Pi's operating system automatically detects your Module 3: [2] 

rpicam-hello --list-cameras

(If the command is not found, try libcamera-hello --list-cameras).
Expected Output:
You should see [0] imx708 listed. This means the camera hardware and the auto-detect firmware are working perfectly. [3] 
------------------------------
## 2. Capture Commands for Headless SSH
When using SSH, you must add the -n or --nopreview flag to prevent the camera software from trying to display a window on a non-existent monitor. [1, 4] 
## Capture a Photo
To take a snapshot immediately and save it as a JPEG, use: [2, 4] 

rpicam-still -n -o image.jpg

(Alternative for older OS: libcamera-still -n -o image.jpg)
## Record a Video
To record a 10-second high-definition video file without opening a desktop stream: [2] 

rpicam-vid -n -t 10000 -o test_video.h264

(Alternative for older OS: libcamera-vid -n -t 10000 -o test_video.h264)
------------------------------
## 3. Remote View: Stream the Camera Live over SSH
If you want to view the camera feed live on your laptop screen via your SSH connection, you have two options:
## Option A: Forward the Preview Window (X11 Forwarding)
If your terminal client has an X-Server running (like MobaXterm on Windows or XQuartz on Mac), log into your Pi using the -X flag: [5, 6] 

ssh -X username@your_pi_ip

Then use the software-rendered preview flag to push the window to your local machine: [1, 5] 

rpicam-hello -t 0 --qt-preview

## Option B: Network Stream (VLC / Network Browser)
A smoother approach for headless environments is sending a network stream from the Pi to your computer. Run this on your Pi:

rpicam-vid -t 0 --inline --listen -o tcp://0.0.0.0:5000

Then, on your personal computer, open media software like VLC Media Player, navigate to Media -> Open Network Stream, and open:

tcp://your_pi_ip:5000

If the camera is not showing up under the --list-cameras command, please tell me:

* What error message do you see in the terminal?
* Is the ribbon cable inserted into the port labeled CAMERA (and not the identical-looking DISPLAY port)?


[1] [https://forums.raspberrypi.com](https://forums.raspberrypi.com/viewtopic.php?t=328686)
[2] [https://raspberry.tips](https://raspberry.tips/en/raspberrypi-tutorials/set-up-raspberry-pi-camera-photos-videos-2026)
[3] [https://medium.com](https://medium.com/@arnav04verma/how-i-set-up-the-raspberry-pi-camera-v3-on-a-raspberry-pi-5-running-ubuntu-24-04-7563d1c61a3b)
[4] [https://raspberrypi.stackexchange.com](https://raspberrypi.stackexchange.com/questions/135888/libcamera-still-hangs-on-pi-3b-running-bullseye-lite-headless)
[5] [https://forums.raspberrypi.com](https://forums.raspberrypi.com/viewtopic.php?t=368867)
[6] [https://forums.raspberrypi.com](https://forums.raspberrypi.com/viewtopic.php?t=161412)
