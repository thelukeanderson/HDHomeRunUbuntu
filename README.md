# HDHomeRun Ubuntu

Watch live TV from an [HDHomeRun](https://www.silicondust.com/) tuner on Ubuntu. `hdhr-tv` opens a TV guide (channels down the side, the next several hours across the top) and plays the channel you pick in VLC.

It's one Python script. It needs VLC and GTK 4, which setup installs if they're missing (GTK 4 is already on most Ubuntu desktops).

## Setup

On each Ubuntu computer you want to watch on:

```
git clone https://github.com/thelukeanderson/HDHomeRunUbuntu.git
cd HDHomeRunUbuntu
python3 hdhr-tv --setup
```

Setup will:

1. Install VLC and the GTK 4 libraries if they're missing (it asks for your password).
2. Install the script to `~/.local/bin/hdhr-tv`.
3. Add **Live TV** to your applications menu.
4. Check that this computer can reach your tuner, and explain what to fix if it can't.

Running setup again is safe; it's also how you update after pulling a newer version.

## Watching

Open **Live TV** from the applications menu, or run `hdhr-tv` in a terminal.

- Shows on now are highlighted, and a red line marks the current time. Scroll sideways to see later shows; **Now** jumps back.
- Click a channel name to watch it straight away.
- Click a show for its details (episode, time, description) and a **Watch** button.
- Start typing to search channel numbers, channel names and show titles.
- Each channel you pick replaces the last one in the same VLC window, so you only use one tuner.
- The guide refreshes itself every 30 minutes, or press the reload button. It follows your system's light or dark style.

To use a specific tuner, give its address: `hdhr-tv 192.168.0.50`.

## How it works

The HDHomeRun is a small web server on your home network:

| Address | Returns |
|---|---|
| `http://<tuner>/discover.json` | Model, firmware, tuner count |
| `http://<tuner>/lineup.json` | Every channel with its stream URL |
| `http://<tuner>:5004/auto/v<channel>` | A live stream of that channel |

`hdhr-tv` finds the tuner through SiliconDust's lookup service (`ipv4-api.hdhomerun.com/discover`), which lists the HDHomeRun devices on your internet connection. It reads the channel list from the tuner, gets the next several hours of listings from SiliconDust's guide service, and hands the chosen stream URL to VLC.

## Requirements and limitations

- **Same network as the tuner.** The computer must be on the same router as the HDHomeRun. If your house has two routers (for example, a Wi-Fi router plugged into your ISP's router), a computer on the second one usually can't reach the tuner. Setup detects this.
- **Ubuntu or Debian-based Linux** for `--setup` (it uses `apt`). On other distributions, install VLC, PyGObject, GTK 4 and libadwaita yourself and run the script directly.
- **Internet access** to find the tuner and load the guide. Without it, pass the tuner's address: `hdhr-tv <ip>`. Reserving that address in your router keeps it from changing.
- **One tuner device.** With several HDHomeRuns, the first one found is used; pass an address to choose another.
- **Tuner count.** Each tuner plays one channel at a time across the whole house (a DUO has two).
- **Encrypted channels are hidden.** Some ATSC 3.0 broadcasts and many cable channels are copy-protected and won't play in VLC.
- **HDHomeRun models from about 2014 onward.** Older models lack the web interface this uses.
- Tested with an HDHomeRun FLEX DUO on US broadcast TV.

## Raspberry Pi

US broadcast TV uses MPEG-2 video, and the Raspberry Pi 5 has no hardware decoder for it, so every frame is decoded and deinterlaced on the CPU. HD channels can stutter as a result. On a Pi, `hdhr-tv` detects this and starts VLC with lighter settings:

- `bob` deinterlacing instead of VLC's heavier default
- VLC's faster decoding shortcuts
- a 2-second network buffer to ride out Wi-Fi hiccups

Other computers use VLC's normal settings. On a Pi, `--setup` also checks whether it has been slowing itself down from overheating or a weak power supply. If it has, use the official 27W USB-C power supply and the Active Cooler. A wired network connection helps too.

## Troubleshooting

`~/.cache/hdhr-tv.log` records the tuner found, each channel picked, and any errors from VLC or the menu. It contains your tuner's address and viewing history, so check it before sharing it publicly.

## Tests

```
python3 -m unittest discover tests
```

The tests don't need a tuner or network access. One test opens a real guide window with made-up channels; it's skipped when there's no display.

## License

Apache 2.0. See [LICENSE](LICENSE).
