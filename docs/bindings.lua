-- Omagenda keybindings.
--
-- Append to ~/.config/hypr/bindings.lua. Hyprland reloads on save; run
-- `hyprctl configerrors` if nothing happens.
--
-- SUPER + CTRL + ALT + D is already the stock clock's calendar, so these
-- deliberately leave it alone.

-- Quick Add: type a sentence, get an event.
o.bind("SUPER + CTRL + N", "Omagenda quick add", "omarchy-shell omagenda quickAdd")

-- The agenda panel. Clicking the bar pill does the same thing.
o.bind("SUPER + CTRL + ALT + N", "Omagenda agenda",
  "omarchy-shell shell summon fixedsupply.omagenda")

-- Sync now. Right-clicking the pill does the same. Omagenda already syncs
-- every five minutes and within seconds of a change you make, so this is
-- for impatience rather than necessity.
-- o.bind("SUPER + CTRL + SHIFT + N", "Omagenda sync now", "omarchy-shell omagenda sync")
