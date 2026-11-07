# HDHomeRun Ubuntu

Watch live TV from an [HDHomeRun](https://www.silicondust.com/) tuner on Ubuntu. `hdhr-tv` opens a channel menu showing what's on now and what's next, and plays the channel you pick in VLC.

It's one Python script with no dependencies beyond VLC and Zenity, which setup installs for you.

## Setup

On each Ubuntu computer you want to watch on:

```
git clone https://github.com/thelukeanderson/HDHomeRunUbuntu.git
cd HDHomeRunUbuntu
python3 hdhr-tv --setup
```

Setup will:

1. Install VLC and Zenity if they're missing (it asks for your password).
2. Install the script to `~/.local/bin/hdhr-tv`.
3. Add **Live TV** to your applications menu.
4. Check that this computer can reach your tuner, and explain what to fix if it can't.

Running setup again is safe; it's also how you update after pulling a newer version.

## Watching

Open **Live TV** from the applications menu, or run `hdhr-tv` in a terminal.

- Type to search the channel list by number or name.
- Click **Watch** (or double-click) to play. The menu comes back so you can change channels, and each pick replaces the last one in the same VLC window.
- Click **Quit** to close the menu; VLC keeps playing.

To use a specific tuner, give its address: `hdhr-tv 192.168.0.50`.

## How it works

The HDHomeRun is a small web server on your home network:

| Address | Returns |
|---|---|
| `http://<tuner>/discover.json` | Model, firmware, tuner count |
| `http://<tuner>/lineup.json` | Every channel with its stream URL |
| `http://<tuner>:5004/auto/v<channel>` | A live stream of that channel |

`hdhr-tv` finds the tuner through SiliconDust's lookup service (`ipv4-api.hdhomerun.com/discover`), which lists the HDHomeRun devices on your internet connection. It reads the channel list from the tuner, gets now/next listings from SiliconDust's guide service, and hands the chosen stream URL to VLC.

## Requirements and limitations

- **Same network as the tuner.** The computer must be on the same router as the HDHomeRun. If your house has two routers (for example, a Wi-Fi router plugged into your ISP's router), a computer on the second one usually can't reach the tuner. Setup detects this.
- **Ubuntu or Debian-based Linux** for `--setup` (it uses `apt`). On other distributions, install `vlc` and `zenity` yourself and run the script directly.
- **Internet access** to find the tuner and load the guide. Without it, pass the tuner's address: `hdhr-tv <ip>`. Reserving that address in your router keeps it from changing.
- **One tuner device.** With several HDHomeRuns, the first one found is used; pass an address to choose another.
- **Tuner count.** Each tuner plays one channel at a time across the whole house (a DUO has two).
- **Encrypted channels are hidden.** Some ATSC 3.0 broadcasts and many cable channels are copy-protected and won't play in VLC.
- **HDHomeRun models from about 2014 onward.** Older models lack the web interface this uses.
- Tested with an HDHomeRun FLEX DUO on US broadcast TV.

## Troubleshooting

`~/.cache/hdhr-tv.log` records the tuner found, each channel picked, and any errors from VLC or the menu. It contains your tuner's address and viewing history, so check it before sharing it publicly.

## Tests

```
python3 -m unittest discover tests
```

The tests don't need a tuner, network access, or a display.

## License

Apache 2.0. See [LICENSE](LICENSE).
