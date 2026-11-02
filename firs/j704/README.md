# J704 speaker DSP, initial profile

This profile is for the MacBook Pro 14-inch with the base M5 SoC (J704).
It takes stereo at 48 kHz and outputs six channels in amplifier order:
left woofer 1, right woofer 1, left woofer 2, right woofer 2, left tweeter,
right tweeter. It requires the separate `AppleJ704` speaker card on PCM 1,
the J704 UCM profile, and speakersafetyd with its J704 protection profile.
The headphone jack is a separate card. The microphone array uses a separate
AOP card and the microphone profile described below.

The current tuning was used on a J704 running Linux. It remains a work in
progress, rather than a completed acoustic calibration or an exact copy of
the complete macOS processing chain. Other M5 models are not covered.

## Processing and coefficient provenance

The graph uses PipeWire builtins and LSP LV2 plugins: loudness normalization,
linear and odd-harmonic bass processing, stereo matrix EQ, multiband
compression, per-driver EQ and output limiters. The WAV files are mono
Float32 impulse responses at 48 kHz, used as convolution coefficients.
They are not audio recordings.

The linear responses were generated offline from the AID39 speaker model
using synthetic impulses in an isolated user process, then truncated for
convolution. The bass harmonic filters were generated numerically. The
compressor thresholds and knees were fitted to synthetic steady-state
responses; LSP replaces the nonlinear processors. This set uses the `_3`
speaker-ID tuning variant. Automatic selection of other speaker-ID variants
is not implemented, and the model alone does not identify a unit's variant.

No Apple executable, firmware, original preset/graph file, device-tree dump,
unit identifier or individual speaker calibration is included. These files
contain the model response and our Linux processing configuration. They
are distributed under this repository's MIT license.

## Volume-dependent processing

`j704-speaker-volume-eq` follows `audio_effect.j704` in the user's PipeWire
session. It crossfades four stereo EQ banks at normalized volume coordinates
0, 0.125, 0.5 and 1. The coordinate is the cube of the volume reported by
`wpctl`; this is the chosen Linux policy, not a recovered macOS slider law.
The helper also compensates the sink gain around the nonlinear bass branch,
bounded to 40 dB. The selected bank and gain controls are in `volume-eq.json`.

`make install` installs and enables its user service for PipeWire. It needs
Python 3, `pw-dump`, `pw-cli` and `wpctl`. On systems without the matching
speaker sink the helper remains idle. Existing sessions need a user service
manager reload and a normal audio-session restart to pick up an installation.

The limiters and this EQ helper do not replace thermal protection.
speakersafetyd and the kernel's speaker-volume interlock remain required.
The current approximation uses independent stereo limiters for the two
woofer pairs; it does not reproduce the native four-woofer shared detector.

The volume helper can be checked without audio devices with
`python3 tests/j704-volume-eq.py` from the repository root.

## Microphone array

The J704 AOP card exposes the three microphones on `hw:AppleJ704AOP,1` as
packed Float32 at 48 kHz. Use the matching three-channel PCM-1 UCM profile.
WirePlumber hides that raw source and creates `MacBook Pro Microphone`, a
mono source, through `mic.json`.

The graph applies one 4096-tap FIR to each capsule and sums the results.
These are linear approximations of the platform's AID39 General recording
profile, identified offline using synthetic white noise. The WAV files
contain 48 kHz Float32 convolution coefficients, not captured audio, an
Apple executable, an original Apple graph, or individual-unit calibration.
They use this repository's MIT license. Generation timestamps are omitted.

The inferred channel order is ALSA AUX0/1/2 to native Mic0/1/2 on the shared
LEAP stream; acoustic verification of individual capsule ordering remains
pending. Removing 1024 samples of pure model delay leaves about 9 ms of
model delay; end-to-end device latency is not established by that figure.
The approximation matched the reference with about
-41.5 dB relative error on synthetic noise and -38.3 dB on a room recording;
the PipeWire convolution matched the same FIR calculation to about -125 dB.
This does not implement adaptive echo cancellation or qualify every native
recording mode. The lid jack reports the hardware microphone disconnect.
