-- Shared by left.conf and right.conf: palette, which monitor, window setup.
--
-- conky runs as an X11 client (under XWayland on a Wayland desktop). The
-- screens are laid out for a 2160 x 3840 portrait monitor - a rotated 4K
-- panel; under KDE with XWayland scaling set to "apply scaling themselves",
-- that is what XWayland reports whatever the Wayland scale factor.
local M = {}

M.dir = debug.getinfo(1, 'S').source:sub(2):match('(.*/)') or './'

function M.palette()
  local p = {}
  local f = io.open(M.dir .. 'palette.css')
  if f then
    for k, v in f:read('a'):gmatch('%-%-([%w%-]+):%s*#(%x%x%x%x%x%x)') do p[k] = v end
    f:close()
  end
  return setmetatable(p, { __index = function() return 'ffffff' end })
end

-- Xinerama head for a screen. NMS_CONKY_OUTPUT names an output (e.g. DP-2);
-- otherwise `side` picks the leftmost or rightmost monitor, which is the
-- natural home for a left or right panel.
function M.head(side)
  local want = os.getenv('NMS_CONKY_OUTPUT')
  local p = io.popen('xrandr --listmonitors 2>/dev/null')
  if not p then return 0 end
  local best, best_x
  for line in p:lines() do
    local i, x, name = line:match('^%s*(%d+):%s+%S+%s+%d+/%d+x%d+/%d+%+(%-?%d+)%+%-?%d+%s+(%S+)%s*$')
    if i then
      i, x = tonumber(i), tonumber(x)
      if want then
        if name == want then best = i; break end
      elseif best_x == nil or (side == 'left' and x < best_x) or (side == 'right' and x > best_x) then
        best, best_x = i, x
      end
    end
  end
  p:close()
  return best or 0
end

-- conky multiplies every pixel setting (gaps, sizes, ${goto}, ${voffset},
-- graph sizes) by Xft.dpi / 96, but not font pixel sizes. KDE sets Xft.dpi to
-- 124 under XWayland, which pushed the layout ~29% past the right edge. So
-- pixel values are divided by the same factor here, and conky scales them
-- back to exactly what was meant.
function M.scale()
  local p = io.popen('xrdb -query 2>/dev/null')
  local out = p and p:read('a') or ''
  if p then p:close() end
  local dpi = tonumber(out:match('Xft%.dpi:%s*([%d%.]+)'))
  return (dpi and dpi > 0) and dpi / 96 or 1
end

-- Rewrite the pixel arguments in conky text by the dpi factor.
function M.unscale(text, s)
  s = s or M.scale()
  local function px(n) return tostring(math.floor(tonumber(n) / s + 0.5)) end
  text = text:gsub('%${(%a+) (%-?%d+)}', function(cmd, n)
    if cmd == 'goto' or cmd == 'voffset' or cmd == 'offset' then return '${' .. cmd .. ' ' .. px(n) .. '}' end
  end)
  -- graphs: "<height>,<width>"
  return (text:gsub('(graph [^}]-)(%d+),(%d+)', function(pre, h, w) return pre .. px(h) .. ',' .. px(w) end))
end

function M.config(over)
  local pal = M.palette()
  local cfg = {
    out_to_x = true,
    out_to_wayland = false,
    own_window = true,
    own_window_type = 'normal',
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_transparent = false,
    own_window_argb_visual = false,
    own_window_colour = pal.page,
    double_buffer = true,

    -- conky grows the window outward past the text area by roughly its
    -- margin; these values land a 2160 x 3840 window at the head's origin.
    -- conky scales pixel settings by the X server's dpi; this assumes 96.
    alignment = 'top_left',
    gap_x = 40,
    gap_y = 40,
    minimum_width = 2082,
    maximum_width = 2082,
    minimum_height = 3763,
    border_inner_margin = 40,
    border_outer_margin = 0,
    border_width = 0,

    use_xft = true,
    override_utf8_locale = true,
    font = 'Noto Sans:pixelsize=30',
    default_color = pal['ink-1'],
    draw_shades = false,
    draw_outline = false,
    draw_borders = false,
    draw_graph_borders = false,

    update_interval = 2,
    no_buffers = true,
    text_buffer_size = 32768,
    max_user_text = 65536,
  }
  for k, v in pairs(over or {}) do cfg[k] = v end
  local s = M.scale()
  for _, k in ipairs({ 'gap_x', 'gap_y', 'minimum_width', 'maximum_width', 'minimum_height',
                       'border_inner_margin', 'border_outer_margin' }) do
    if cfg[k] then cfg[k] = math.floor(cfg[k] / s + 0.5) end
  end
  return cfg
end

return M
