# From the personal Alpha/Shadows prototype

The v0.1 package is a separate distribution, not an in-place replacement for
private `~/.pi/agent` files. It uses a new app ID, layer namespace, runtime
namespace and XDG config directory. It does not read the old personality state,
copy relationship memory, patch another subagent tool, or install legacy launchers.

1. Back up your existing extensions/configuration and preserve your customized
   agent definitions. Do not delete the old companion while evaluating this one.
2. Test the package in an isolated Pi agent directory, or a fresh profile first.
   `tests/pi_smoke.py` demonstrates isolated installation without any model call.
3. For normal use, disable the old bridge before loading this package; `/shadows`
   and `/shadows-mode` must have only one owner. Disable the old personality
   injector if using the package's personas, or set `persona:false` in the new
   config to retain your own. Nothing changes these files automatically.
4. Install the Git package and `/reload`. Run `/shadows doctor`, then `/shadows`.
5. Select a pack. Use `shadows_delegate` for character streams, or adapt your
   existing runner to the versioned event contract. The previous private
   `shadows:agent` event is not consumed by this package.
6. Update personal shortcuts/autostart deliberately if you want the new app.
   The original Super+Shift+A wrapper continues launching the original app
   until you change it. This package installs no desktop-wide keybindings.

The `neutral` pack is the default. Character packs use portable agent definitions
and do not overwrite your `~/.pi/agent/agents`. Copy role refinements into your
own fork after reviewing them; Pi-managed package clones are resettable on update.

To revert an evaluation, remove the package from Pi and reload, then re-enable
your old bridge/personality setup. The public package has not mutated those files.
