# EchoSense — Hardware Wiring Guide

All GPIO numbers use **BCM (Broadcom) numbering**, which is what the code uses.
Physical pin numbers refer to the **40-pin GPIO header** on the Raspberry Pi 5.

---

## 1. Raspberry Pi 5 — 40-Pin Header Reference

```
                    ┌─────────┐
               3.3V │  1 ●  2 │ 5V
    I2C SDA / GPIO2 │  3    4 │ 5V
    I2C SCL / GPIO3 │  5    6 │ GND
              GPIO4 │  7    8 │ GPIO14  ← UART0 TX  (LiDAR)
                GND │  9   10 │ GPIO15  ← UART0 RX  (LiDAR)
             GPIO17 │ 11   12 │ GPIO18  ← I2S BCLK  (INMP441)
             GPIO27 │ 13   14 │ GND
             GPIO22 │ 15   16 │ GPIO23  ← BUZZER 1
               3.3V │ 17   18 │ GPIO24  ← BUZZER 2
             GPIO10 │ 19   20 │ GND
              GPIO9 │ 21   22 │ GPIO25  ← VIBRATION MOTOR
             GPIO11 │ 23   24 │ GPIO8
                GND │ 25   26 │ GPIO7
              GPIO0 │ 27   28 │ GPIO1
    UART3 TX/ GPIO4 │ 29   30 │ GND
    UART3 RX/ GPIO5 │ 31   32 │ GPIO12  ← LED 1 (PWM0)
             GPIO13 │ 33   34 │ GND     ← LED 2 (PWM1)
  I2S WS   / GPIO19 │ 35   36 │ GPIO16  ← LLM BUTTON
             GPIO26 │ 37   38 │ GPIO20  ← I2S DATA (INMP441)
                GND │ 39   40 │ GPIO21
                    └─────────┘

  GPIO17 → Pin 11   POWER BUTTON
  GPIO26 → Pin 37   SOS BUTTON
  GPIO16 → Pin 36   LLM BUTTON
  GPIO4  → Pin 29   SIM808 TX (Pi transmits → SIM808 receives)
  GPIO5  → Pin 31   SIM808 RX (Pi receives  ← SIM808 transmits)
  GPIO14 → Pin 8    LiDAR TX  (Pi transmits → LiDAR receives)
  GPIO15 → Pin 10   LiDAR RX  (Pi receives  ← LiDAR transmits)
```

---

## 2. Required /boot/firmware/config.txt Additions

Add these lines to enable the second UART and free the primary one from Bluetooth:

```ini
# Free UART0 (GPIO 14/15) from Bluetooth → used by TF-Luna LiDAR
dtoverlay=disable-bt

# Enable UART3 (GPIO 4/5) → used by SIM808
dtoverlay=uart3

# Camera
camera_auto_detect=1

# I2S microphone (only if using INMP441 — skip if using USB mic)
dtoverlay=i2s-mems-mic
```

Reboot after editing.

---

## 3. Hailo AI HAT 2+

| Connection | Details |
|---|---|
| Interface | M.2 HAT+ PCIe slot (underside of Pi 5) |
| Power | Supplied by the HAT+ 5V rail from Pi 5 |
| Ribbon cable | Connect the 16-pin FFC cable between the HAT and Pi 5 PCIe connector |
| No GPIO wiring needed | Hailo communicates over PCIe — plug and play |

> After fitting, run `hailortcli fw-control identify` to confirm the chip is detected.

---

## 4. TF-Luna LiDAR (UART — /dev/ttyAMA0)

| TF-Luna Pin | Wire to | Pi 5 Header |
|---|---|---|
| VCC (red) | 5V | Pin 4 |
| GND (black) | GND | Pin 6 |
| TX (green) | GPIO15 — UART0 RX | Pin 10 |
| RX (white) | GPIO14 — UART0 TX | Pin 8 |

> **Note:** The Pi's TX connects to the sensor's RX, and vice versa — this is standard serial crossover.

---

## 5. SIM808 GPS/GSM Module (UART — /dev/ttyAMA3)

| SIM808 Pin | Wire to | Pi 5 Header |
|---|---|---|
| VCC | 5V | Pin 2 |
| GND | GND | Pin 9 |
| TXD | GPIO5 — UART3 RX | Pin 31 |
| RXD | GPIO4 — UART3 TX | Pin 29 |

> SIM808 runs at 3.3V logic but is 5V tolerant. However, Pi 5 GPIO is 3.3V — no level shifter needed.
>
> Insert a **Nano SIM card** into the SIM808 slot. Attach the GSM antenna to the SMA connector (antenna critical for GPS fix and SMS).

---

## 6. Raspberry Pi Camera — 200° FOV (CSI)

| Connection | Details |
|---|---|
| Connector | 15-pin CSI ribbon cable → **CAM0** or **CAM1** port on Pi 5 |
| Blue side of ribbon | Faces the USB ports on Pi 5 |
| Lock clip | Lift the black clip, insert ribbon, press clip down |

> No GPIO pins used. Camera communicates via CSI (Camera Serial Interface) directly.

---

## 7. Buzzers via IRLZ44N MOSFET + Step-Up Module

The buzzers are rated 3–24V. Drive them at 9–12V using a Step-Up module fed from the battery.

### Circuit (repeat for each buzzer):

```
Pi GPIO ──[10kΩ]──── IRLZ44N Gate
                         │
Pi GND  ──[10kΩ]──── IRLZ44N Gate  ← pull-down to prevent floating
                         │
                     IRLZ44N Source ──── GND

Step-Up Output (+) ──── Buzzer (+)
                         │
                         Buzzer (-)
                         │
                     IRLZ44N Drain ──── (back to GND via MOSFET)

Add 1N4007 flyback diode across Buzzer terminals (cathode toward +)
```

| Signal | GPIO | Pi 5 Pin |
|---|---|---|
| Buzzer 1 control | GPIO23 | Pin 16 |
| Buzzer 2 control | GPIO24 | Pin 18 |

> **Step-Up module:** Input from battery (11–12V), output set to 12V. This powers both buzzers.

---

## 8. Vibration Motor via NPN Transistor (2N2222 or IRLZ44N)

```
Pi GPIO25 ──[1kΩ]──── Transistor Base (or MOSFET Gate)
                           │
Pi GND  ─────────────── Transistor Emitter (Source)

5V ──── Motor (+)
         │
         Motor (-)
         │
       Transistor Collector (Drain)

Add 1N4007 flyback diode across motor terminals (cathode toward +)
```

| Signal | GPIO | Pi 5 Pin |
|---|---|---|
| Vibration motor | GPIO25 | Pin 22 |
| Motor power | 5V | Pin 2 |

---

## 9. LEDs (2× 3W) via IRLZ44N MOSFET

3W LEDs draw ~700–900mA each. Use an IRLZ44N MOSFET as a switch with PWM dimming.

```
Pi GPIO ──[10kΩ]──── IRLZ44N Gate
Pi GND  ──[10kΩ]──── IRLZ44N Gate  ← pull-down

5V ──── LED (+)
         │
         LED (−)  [include current-limiting resistor if LED has no built-in driver]
         │
     IRLZ44N Drain
         │
     IRLZ44N Source ──── GND
```

| Signal | GPIO | Pi 5 Pin |
|---|---|---|
| LED 1 (PWM) | GPIO12 | Pin 32 |
| LED 2 (PWM) | GPIO13 | Pin 33 |

> GPIO12 and GPIO13 are hardware PWM pins — brightness is controlled by the code automatically when ambient light is low.

---

## 10. Audio — Speakers + PAM8403 Amplifier

```
USB Sound Card ──USB──► Pi 5 USB Port
      │
      AUX 3.5mm output
      │
      ├── Left channel  ──► PAM8403 IN-L
      └── Right channel ──► PAM8403 IN-R

PAM8403:
  VCC ──► 5V (Pi Pin 4)
  GND ──► GND (Pi Pin 6)
  OUT-L+ / OUT-L- ──► Speaker 1 (3W 4Ω)
  OUT-R+ / OUT-R- ──► Speaker 2 (3W 4Ω)
```

> The PAM8403 is a Class-D amplifier. Do **not** connect speaker outputs to ground directly — use the differential OUT+ and OUT− terminals.
>
> Set the USB sound card as the default audio device:
> ```bash
> # Check card number
> aplay -l
> # Set default in /etc/asound.conf
> echo 'defaults.pcm.card 1\ndefaults.ctl.card 1' | sudo tee /etc/asound.conf
> ```

---

## 11. Microphone

### Option A — USB Microphone (Recommended)

Plug into any Pi 5 USB port. No GPIO wiring needed. Works immediately with the hailo-apps voice stack.

### Option B — INMP441 MEMS Microphone (I2S)

> **If using this option:** GPIO 18, 19, 20 are consumed by I2S. The code's default button assignments must not use those pins — the wiring below reflects the corrected assignments already in `config.py`.

| INMP441 Pin | Wire to | Pi 5 Header |
|---|---|---|
| VDD | 3.3V | Pin 17 |
| GND | GND | Pin 25 |
| SCK (BCLK) | GPIO18 | Pin 12 |
| WS (LRCLK) | GPIO19 | Pin 35 |
| SD (DATA) | GPIO20 | Pin 38 |
| L/R | GND | Pin 25 |

---

## 12. Buttons (3× Momentary Pushbutton)

All buttons use the Pi's **internal pull-up** resistor (no external resistor needed). Connect one terminal to the GPIO pin and the other to GND.

| Button | GPIO | Pi 5 Pin | Other terminal |
|---|---|---|---|
| LLM (scene describe) | GPIO16 | Pin 36 | GND (Pin 39) |
| SOS (emergency) | GPIO26 | Pin 37 | GND (Pin 39) |
| Power (shutdown) | GPIO17 | Pin 11 | GND (Pin 14) |

---

## 13. Cooling Fans (2× 12V 3010)

Connect directly to the battery 12V rail. These run always-on.

| Fan wire | Connect to |
|---|---|
| Red (+) | Battery 12V (after BMS) |
| Black (−) | Battery GND |

> Optionally, add a small NPN transistor (2N2222) circuit on each fan controlled by a spare GPIO if you want software speed control, but always-on is fine for cooling.

---

## 14. Power System

```
  ┌──────────────────────────────────────────────────────────┐
  │  LiPo Battery Pack  11.3–12V / 5000mAh  with BMS (20A)  │
  └──────────┬───────────────────────────────────────────────┘
             │ 12V rail
             │
     ┌───────┼───────────────────────────────────┐
     │       │                                   │
     ▼       ▼                                   ▼
 DC-DC     Step-Up Module                  Fans (12V)
 Step-Down  (12V → set to 12–24V          directly from
 (12V→5V    for Buzzers)                  battery
  3A+)
     │
     ▼
  5V / 3A+
     │
     ├──► Pi 5 via USB-C (or GPIO 5V pins 2/4)
     ├──► PAM8403 amplifier VCC
     ├──► Vibration motor supply
     └──► SIM808 VCC
```

> **DC-DC Step Down:** Use one rated for at least **5V / 5A** output (Pi 5 can draw up to 5A under full AI load with Hailo HAT). Set output voltage to exactly **5.1V** before connecting.
>
> **BMS:** The 20A BMS protects against overcurrent, overcharge, and deep discharge. Connect battery → BMS → rest of circuit.

---

## 15. Full GPIO Summary Table

| GPIO | BCM | Pi Pin | Connected To |
|---|---|---|---|
| GPIO4 | 4 | 29 | SIM808 TXD → Pi RX (UART3) |
| GPIO5 | 5 | 31 | SIM808 RXD ← Pi TX (UART3) |
| GPIO12 | 12 | 32 | LED 1 (PWM0) via IRLZ44N |
| GPIO13 | 13 | 33 | LED 2 (PWM1) via IRLZ44N |
| GPIO14 | 14 | 8 | LiDAR TXD → Pi RX (UART0) |
| GPIO15 | 15 | 10 | LiDAR RXD ← Pi TX (UART0) |
| GPIO16 | 16 | 36 | LLM Button → GND |
| GPIO17 | 17 | 11 | Power Button → GND |
| GPIO18 | 18 | 12 | INMP441 BCLK (I2S) |
| GPIO19 | 19 | 35 | INMP441 WS/LRCLK (I2S) |
| GPIO20 | 20 | 38 | INMP441 DATA (I2S) |
| GPIO23 | 23 | 16 | Buzzer 1 via IRLZ44N |
| GPIO24 | 24 | 18 | Buzzer 2 via IRLZ44N |
| GPIO25 | 25 | 22 | Vibration Motor via transistor |
| GPIO26 | 26 | 37 | SOS Button → GND |

> GPIO18–20 are reserved for I2S mic. If using a USB mic instead, GPIO18–20 are free.

---

## 16. Assembly Checklist

- [ ] Hailo AI HAT seated and secured on Pi 5 M.2 slot
- [ ] Camera ribbon cable inserted (blue tab facing USB ports), lock clicked
- [ ] TF-Luna connected on GPIO 14/15 (TX/RX crossed)
- [ ] SIM808 connected on GPIO 4/5 (TX/RX crossed), SIM + antenna installed
- [ ] Buzzers each connected through IRLZ44N + Step-Up module
- [ ] Vibration motor connected through transistor with flyback diode
- [ ] LEDs connected through IRLZ44N on GPIO 12/13 (PWM)
- [ ] PAM8403 powered, USB sound card plugged in, speakers connected
- [ ] Microphone connected (USB or INMP441 I2S)
- [ ] 3 buttons wired to GPIO 16, 26, 17 with other terminal to GND
- [ ] Fans wired directly to 12V battery rail
- [ ] DC-DC step-down set to 5.1V, rated ≥5A, connected to Pi USB-C
- [ ] Step-Up module set to 12V for buzzers
- [ ] BMS connected between battery cells and output rail
- [ ] /boot/firmware/config.txt updated with dtoverlay lines (Section 2)
- [ ] Reboot and run: `hailortcli fw-control identify` to confirm Hailo chip
- [ ] Run: `python3 main.py` to start EchoSense
