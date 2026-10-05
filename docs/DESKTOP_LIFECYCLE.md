# Desktop launchers

The macOS and Windows launchers use one shared Tk adapter. Configuration and log
widgets are updated only by the Tk main loop; a bounded controller queue holds
up to 256 log events and one latest state. The visible log retains 500 lines.
Settings and logs resize, standard keyboard focus is available, and Control-S
(Command-S on macOS) saves while the owned child is stopped. Blank secret and
model fields preserve saved values. No model catalog or price is inferred.

`starting`, `connecting`, `ready`, `degraded`, `stopping` and `exited` describe
different states. Process existence alone means connecting. A launcher health
probe uses only `127.0.0.1`, disables proxies and redirects, limits the response
to 8 KiB and waits at most 0.75 seconds. The launched child's console echoes an
ephemeral instance nonce only for a matching `X-Launcher-Probe` header. This
header provides no API authorization. Ordinary public health responses retain
their existing minimal shape. An existing console from another launcher or
launchd instance does not satisfy the matching probe.

Closing the window requests cooperative shutdown with a 12-second deadline and
keeps the window open until the owned group/job, primary child and output reader
have all finished. Unconfirmed shutdown retains admission and rejects restart.
The launcher never adopts a process by name or discovers a service PID. An
existing bridge can be borrowed by the combined runner; it is outside the new
child's group/job and is not terminated by launcher shutdown.

On POSIX, the new child starts a new session. An unreaped leader reserves the
group identity until signalling is sealed; Linux uses `waitid(WNOWAIT)` and
macOS uses a `kqueue` exit observation. Exit observation is not the final exit
code. Darwin can return EPERM for a group containing only zombies, as its
[kernel group signal implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c)
filters them. EPERM is also possible for protected members: it never proves
closure. After the final signal attempt the controller seals further group
signals, reaps only its own leader, and requires an absent group. A remaining
or uninspectable group keeps ownership pending.

Windows uses an unnamed Job with kill-on-close, assigned using the owned
`Popen` process HANDLE before the child receives its stdin startup permit.
Cooperative stop uses the private stdin pipe; forced termination uses the Job
after the deadline. No process-tree or process-name termination fallback exists.
See Microsoft's [Job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [assignment rules](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject).
Native Windows execution is required to verify these APIs.

Both source and frozen launchers dispatch `--run-bot`, `--run-bridge` and
`--run-research-worker` before Tk or application setup. The research worker
receives credentials only in stdio, keeps its private environment and deadline,
and rejects custom script overrides in frozen mode. Offline provider refusal
still occurs before launching a real SDK worker. Windowed frozen workers restore
their inherited stdio handles, following PyInstaller's
[windowed stdio constraints](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
Source launchers can locate matching Tcl/Tk libraries inside a relocated Python
distribution without installing or changing the user's runtime.

## Engineering checks

Run `python scripts/check_desktop_lifecycle.py` with the locked desktop profile
on the target platform. It creates a temporary synthetic home under the owned
scratch directory, records native Tk call thread IDs, checks layout/focus/scaling,
and rehearses window close with an owned child and descendant. An unrelated
fixture process must remain alive. It opens a fixture window but starts no bot,
bridge, account connection or real search provider.

The native desktop workflow runs this check before building. The builder also
runs the windowed executable's offline research stdio mode and a separate
`--smoke-ui` check. `Inebotten-runtime-smoke-PLATFORM.json` records those results;
the asset-only smoke receipt remains separate and does not claim it opened UI.
The frozen UI check does not exercise child process ownership.

These checks demonstrate engineering behavior with fixtures. They do not prove
live bot readiness, application data shutdown under a real workload, signing,
notarization, human accessibility/keyboard acceptance, every display scaling
configuration, or native Windows behavior from a macOS test run.
