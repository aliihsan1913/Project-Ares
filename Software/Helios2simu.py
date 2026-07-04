import pygame
import sys
import math
import random
from collections import deque
from enum import Enum, auto

# ─── SABITLER ────────────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 720
FPS = 60
MA_WINDOW = 12
MAX_PARTICLES = 500
PHYS_DT = 1.0 / 200.0

BG_COLOR = (2, 6, 14)
STAR_COLOR = (200, 220, 255)
SUN_COLOR = (255, 224, 96)
HUD_TEXT = (174, 232, 255)
HUD_LABEL = (70, 130, 180)
PARTICLE_PROTON = (140, 200, 255)
PARTICLE_ION = (255, 220, 100)

MARS_X = int(WIDTH * 0.72)
MARS_Y = int(HEIGHT * 0.50)
MARS_R = 72
SUN_X = -80
SUN_Y = HEIGHT // 2

CRITICAL_TEMP = 1.0
RECOVERY_TEMP = 0.3
CAP_MAX = 100.0


# ─── STATE MACHINE ───────────────────────────────────────────────────────────
class State(Enum):
    IDLE = auto()
    LOW_THREAT = auto()
    STORM_ALERT = auto()
    OVERDRIVE = auto()
    CRITICAL_FAILURE = auto()
    RECOVERY_MODE = auto()


STATE_CFG = {
    #                       label               badge_col         shield_a
    State.IDLE: ("IDLE", (100, 255, 140), 40),
    State.LOW_THREAT: ("LOW THREAT", (200, 220, 60), 80),
    State.STORM_ALERT: ("STORM ALERT", (255, 160, 30), 130),
    State.OVERDRIVE: ("OVERDRIVE", (180, 80, 255), 200),
    State.CRITICAL_FAILURE: ("CRITICAL FAILURE", (255, 40, 40), 0),
    State.RECOVERY_MODE: ("RECOVERY MODE", (80, 180, 255), 60),
}

FLUX_THRESHOLDS = {
    State.IDLE: (0.0, 1.2),
    State.LOW_THREAT: (1.2, 1.8),
    State.STORM_ALERT: (1.8, 2.4),
    State.OVERDRIVE: (2.4, 9.9),
}

STATE_DESCRIPTIONS = {
    State.IDLE: "System nominal — base power",
    State.LOW_THREAT: "Solar wind detected — shield online",
    State.STORM_ALERT: "CME incoming — capacitors charging",
    State.OVERDRIVE: "Max power — heat rising fast!",
    State.CRITICAL_FAILURE: "THERMAL QUENCH — shield offline!",
    State.RECOVERY_MODE: "Cooling down — resyncing RF...",
}


# ─── PID KONTROLCÜ ───────────────────────────────────────────────────────────
class PIDController:
    def __init__(self, kp=0.55, ki=0.08, kd=0.12):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.prev_error = 0.0
        self.output = 0.0

    def update(self, setpoint, measured, dt):
        error = setpoint - measured
        self.integral += error * dt
        self.integral = max(-2.0, min(2.0, self.integral))
        derivative = (error - self.prev_error) / max(dt, 1e-6)
        self.prev_error = error
        raw = self.kp * error + self.ki * self.integral + self.kd * derivative
        self.output = max(0.0, min(1.0, raw))
        return self.output

    def reset(self):
        self.integral = 0.0
        self.prev_error = 0.0
        self.output = 0.0


# ─── YARDIMCI ────────────────────────────────────────────────────────────────
def noise(t, freq, amp):
    return (math.sin(t * freq) * amp
            + math.sin(t * freq * 2.3 + 1.0) * amp * 0.4
            + math.sin(t * freq * 0.7 + 2.0) * amp * 0.3)


def moving_average(samples, n):
    if not samples: return 0.0
    w = list(samples)[-n:]
    return sum(w) / len(w)


def get_font(size, bold=False):
    for name in ["Consolas", "Lucida Console", "DejaVu Sans Mono", "Liberation Mono", "Courier New"]:
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f: return f
        except:
            pass
    return pygame.font.Font(None, size)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def bar_rect(surf, x, y, w, h, val, mx, col, bg=(20, 50, 80)):
    pygame.draw.rect(surf, bg, (x, y, w, h))
    pygame.draw.rect(surf, col, (x, y, int(w * min(1.0, val / max(mx, 1e-6))), h))


# ─── YILDIZLAR & GÖRSEL EFEKTLER ─────────────────────────────────────────────
class Star:
    def __init__(self):
        self.x = random.randint(0, WIDTH)
        self.y = random.randint(0, HEIGHT)
        self.r = random.uniform(0.4, 1.5)
        self.a = random.randint(55, 150)

    def draw(self, surf):
        s = pygame.Surface((4, 4), pygame.SRCALPHA)
        pygame.draw.circle(s, (*STAR_COLOR, self.a), (2, 2), max(1, int(self.r)))
        surf.blit(s, (int(self.x) - 2, int(self.y) - 2))


class CMEBurst:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.radius = 10
        self.life = 1.0
        self.active = True

    def update(self):
        self.radius += 25
        self.life -= 0.015
        if self.life <= 0:
            self.active = False

    def draw(self, surf):
        if not self.active: return
        a = int(self.life * 120)
        s = pygame.Surface((self.radius * 2, self.radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (255, 120, 30, a), (self.radius, self.radius), self.radius, max(1, int(self.life * 15)))
        surf.blit(s, (int(self.x) - self.radius, int(self.y) - self.radius))


# ─── PARÇACIK ────────────────────────────────────────────────────────────────
class Particle:
    def __init__(self, flux_mult=1.0, is_cme=False):
        spread = HEIGHT * 0.72 if not is_cme else HEIGHT * 0.9
        self.x = float(SUN_X + 90)
        self.y = MARS_Y + random.uniform(-spread / 2, spread / 2)

        base_spd = random.uniform(3.8, 6.8) if not is_cme else random.uniform(8.0, 14.0)
        spd = base_spd * (0.8 + flux_mult * 0.4)
        ang = random.uniform(-0.14, 0.14) if not is_cme else random.uniform(-0.25, 0.25)

        self.vx = spd * math.cos(ang)
        self.vy = spd * math.sin(ang) + random.uniform(-0.35, 0.35)
        self.life = 1.0
        self.decay = random.uniform(0.004, 0.009) if not is_cme else random.uniform(0.008, 0.015)
        self.size = random.uniform(1.0, 2.8) if not is_cme else random.uniform(2.0, 4.0)
        self.kind = 0 if random.random() < 0.65 else 1
        self.trail = []
        self.deflected = False
        self.is_cme = is_cme

    def try_deflect(self, shield_r, state, beam_current):
        if state in (State.CRITICAL_FAILURE, State.IDLE):
            return
        dx = self.x - MARS_X
        dy = self.y - MARS_Y
        dist = max(math.hypot(dx, dy), 1e-6)   # sıfıra bölme koruması
        eff_r = shield_r * (0.6 + beam_current * 0.5)

        if dist < eff_r + 8 and not self.deflected:
            nx, ny = dx / dist, dy / dist
            spd = math.hypot(self.vx, self.vy)
            deflect_force = random.uniform(0.7, 1.3) if not self.is_cme else random.uniform(0.9, 1.5)
            self.vx = nx * spd * deflect_force
            self.vy = ny * spd * deflect_force + random.uniform(-0.5, 0.5)
            self.deflected = True
            self.life -= 0.15

    def update(self):
        self.trail.append((self.x, self.y))
        if len(self.trail) > 7: self.trail.pop(0)
        self.x += self.vx
        self.y += self.vy
        self.life -= self.decay

    def hits_mars(self):
        return math.hypot(self.x - MARS_X, self.y - MARS_Y) < MARS_R

    def alive(self):
        return (self.life > 0 and
                -20 < self.x < WIDTH + 20 and
                -20 < self.y < HEIGHT + 20)

    def draw(self, surf):
        base = PARTICLE_PROTON if self.kind == 0 else PARTICLE_ION
        if self.is_cme: base = (255, 100, 50)
        if self.deflected: base = (200, 160, 255)

        alpha = int(self.life * 210)
        for i, (tx, ty) in enumerate(self.trail):
            ta = int(alpha * (i / len(self.trail)) * 0.3)
            s = pygame.Surface((4, 4), pygame.SRCALPHA)
            pygame.draw.circle(s, (*base, ta), (2, 2), 1)
            surf.blit(s, (int(tx) - 2, int(ty) - 2))
        r = max(1, int(self.size))
        s = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*base, alpha), (r + 1, r + 1), r)
        surf.blit(s, (int(self.x) - r, int(self.y) - r))


class ImpactFlash:
    def __init__(self, x, y):
        self.x, self.y, self.life = x, y, 1.0

    def update(self): self.life -= 0.07

    def alive(self):  return self.life > 0

    def draw(self, surf):
        r = int(2 * (1 - self.life) + 2)
        a = int(self.life * 200)
        s = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (255, 130, 50, a), (r + 1, r + 1), r)
        surf.blit(s, (int(self.x) - r, int(self.y) - r))


# ─── ÇİZİM: JURY MODE (Taktik Ekran) ─────────────────────────────────────────
def draw_tactical_grid(surf, font_s, beam_current):
    for x in range(0, WIDTH, 100):
        pygame.draw.line(surf, (30, 60, 90, 40), (x, 0), (x, HEIGHT), 1)
    for y in range(0, HEIGHT, 100):
        pygame.draw.line(surf, (30, 60, 90, 40), (0, y), (WIDTH, y), 1)

    for r in [MARS_R + 50, MARS_R + 150, MARS_R + 250]:
        pygame.draw.circle(surf, (50, 120, 180, 60), (MARS_X, MARS_Y), r, 1)
        lbl = font_s.render(f"{r}km", True, (50, 120, 180, 100))
        surf.blit(lbl, (MARS_X + 5, MARS_Y - r + 5))

    pygame.draw.line(surf, (70, 180, 255, 100), (MARS_X, 0), (MARS_X, HEIGHT), 1)
    pygame.draw.line(surf, (70, 180, 255, 100), (0, MARS_Y), (WIDTH, MARS_Y), 1)

    if beam_current > 0.1:
        v_radius = int((MARS_R + 28) * (0.6 + beam_current * 0.5)) + 15
        pygame.draw.arc(surf, (160, 100, 255, 150),
                        (MARS_X - v_radius, MARS_Y - v_radius, v_radius * 2, v_radius * 2),
                        math.pi / 2, 3 * math.pi / 2, 2)
        lbl = font_s.render("B-FIELD INDUCTION", True, (160, 100, 255))
        surf.blit(lbl, (MARS_X - v_radius - 110, MARS_Y))


# ─── ÇİZİM: GÜNEŞ ────────────────────────────────────────────────────────────
def draw_sun(surf, state, sim_time):
    jitter = 0
    if state in (State.STORM_ALERT, State.OVERDRIVE):
        jitter = int(math.sin(sim_time * 18) * 3)
    for radius, alpha in [(240, 8), (150, 18), (90, 42), (50, 80)]:
        g = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        col = (255, 100, 20) if state == State.OVERDRIVE else (255, 170, 30)
        pygame.draw.circle(g, (*col, alpha), (radius, radius), radius)
        surf.blit(g, (SUN_X - radius, SUN_Y - radius + jitter))
    pygame.draw.circle(surf, SUN_COLOR, (SUN_X, SUN_Y + jitter), 54)
    pygame.draw.circle(surf, (255, 255, 210), (SUN_X - 10, SUN_Y - 8 + jitter), 16)


# ─── ÇİZİM: MARS ─────────────────────────────────────────────────────────────
def draw_mars(surf, font_s, state, show_ui):
    R = MARS_R
    cx, cy = MARS_X, MARS_Y
    D = R * 2 + 4
    mc = (R + 2, R + 2)
    ms = pygame.Surface((D, D), pygame.SRCALPHA)

    pygame.draw.circle(ms, (115, 30, 14, 255), mc, R)
    clip_mask = pygame.Surface((D, D), pygame.SRCALPHA)
    pygame.draw.circle(clip_mask, (255, 255, 255, 255), mc, R)

    light = pygame.Surface((D, D), pygame.SRCALPHA)
    pygame.draw.circle(light, (215, 105, 55, 200), (mc[0] - 16, mc[1] - 14), int(R * 0.92))
    light.blit(clip_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    ms.blit(light, (0, 0))

    for ox, oy, cr, a in [(20, -12, 13, 60), (-26, 16, 10, 55), (4, 26, 8, 50), (-8, -28, 8, 45)]:
        cs = pygame.Surface((cr * 2, cr * 2), pygame.SRCALPHA)
        pygame.draw.circle(cs, (55, 12, 4, a), (cr, cr), cr)
        ms.blit(cs, (mc[0] + ox - cr, mc[1] + oy - cr))

    night = pygame.Surface((D, D), pygame.SRCALPHA)
    for i in range(R, 0, -3):
        ratio = 1.0 - (i / R)
        a = int(185 * ratio ** 1.6)
        pygame.draw.circle(night, (0, 0, 0, a), (mc[0] + 34, mc[1] + 6), i)
    night.blit(clip_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    ms.blit(night, (0, 0))

    surf.blit(ms, (cx - R - 2, cy - R - 2))

    if state == State.CRITICAL_FAILURE:
        pulse = pygame.Surface((D + 20, D + 20), pygame.SRCALPHA)
        a = int(abs(math.sin(pygame.time.get_ticks() * 0.006)) * 80)
        pygame.draw.circle(pulse, (255, 30, 20, a), (R + 12, R + 12), R + 6)
        surf.blit(pulse, (cx - R - 12, cy - R - 12))

    if show_ui:
        shield_txt = "[NO SHIELD]" if state == State.CRITICAL_FAILURE else "[SHIELD ACTIVE]"
        col = (255, 80, 60) if state == State.CRITICAL_FAILURE else (190, 120, 80)
        lbl = font_s.render(f"MARS  {shield_txt}", True, col)
        surf.blit(lbl, (cx - lbl.get_width() // 2, cy + R + 10))


# ─── ÇİZİM: AURORA & KALKAN (Spectroscopy) ──────────────────────────────────
def draw_shield_aurora(surf, state, sim_time, shield_alpha, beam_current, temperature):
    if state == State.CRITICAL_FAILURE:
        return

    col_low = (80, 255, 120)
    col_mid = (80, 200, 255)
    col_high = (180, 80, 255)

    if beam_current < 0.5:
        aurora_col = lerp_color(col_low, col_mid, beam_current * 2)
    else:
        aurora_col = lerp_color(col_mid, col_high, (beam_current - 0.5) * 2)

    if temperature > 0.7:
        flicker = int(math.sin(sim_time * 30) * 30)
        aurora_col = (min(255, aurora_col[0] + flicker), aurora_col[1], aurora_col[2])

    shield_r = MARS_R + 28
    eff_r = int(shield_r * (0.6 + beam_current * 0.5))

    if shield_alpha > 5:
        for thick, am in [(20, 0.12), (12, 0.28), (5, 0.65), (2, 1.0)]:
            ring = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            a = int(shield_alpha * am)
            pygame.draw.circle(ring, (*aurora_col, a),
                               (MARS_X, MARS_Y), eff_r + thick // 2, thick)
            surf.blit(ring, (0, 0))

    count = {
        State.IDLE: 12, State.LOW_THREAT: 16,
        State.STORM_ALERT: 22, State.OVERDRIVE: 40, State.RECOVERY_MODE: 10
    }.get(state, 10)

    for i in range(count):
        angle = (sim_time * 0.8 + i * (2 * math.pi / count) + math.sin(sim_time * 1.2 + i) * 0.3)
        r_off = eff_r + 10 + math.sin(sim_time * 2.0 + i * 1.1) * 10
        ax = MARS_X + int(r_off * math.cos(angle))
        ay = MARS_Y + int(r_off * math.sin(angle) * 0.65)
        sz = random.randint(4, 12) if state == State.OVERDRIVE else random.randint(2, 7)
        aa = int(shield_alpha * random.uniform(0.4, 0.9))
        s = pygame.Surface((sz * 2, sz * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*aurora_col, aa), (sz, sz), sz)
        surf.blit(s, (ax - sz, ay - sz))


# ─── ÇİZİM: SOL HUD ──────────────────────────────────────────────────────────
def draw_hud_left(surf, font, font_s,
                  raw_flux, flt_flux, temperature,
                  beam_current, cyclotron_watts, rf_sync,
                  cap_charge, count, sim_t, dt_ms):
    pw, ph = 225, 360
    px, py = 16, 16
    panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
    panel.fill((0, 18, 38, 180))
    pygame.draw.rect(panel, (70, 160, 240, 55), (0, 0, pw, ph), 1)

    pygame.draw.line(panel, (70, 160, 240), (0, 0), (15, 0), 2)
    pygame.draw.line(panel, (70, 160, 240), (0, 0), (0, 15), 2)
    surf.blit(panel, (px, py))

    def row(label, value, color, bar_val=None, bar_max=1.0, bar_col=(70, 160, 255)):
        nonlocal yo
        surf.blit(font_s.render(label, True, HUD_LABEL), (px + 10, py + yo));
        yo += 14
        surf.blit(font.render(value, True, color), (px + 10, py + yo));
        yo += 18
        if bar_val is not None:
            bar_rect(surf, px + 10, py + yo, pw - 20, 4, bar_val, bar_max, bar_col)
            yo += 9
        yo += 4

    yo = 12
    row("SOLAR FLUX  RAW", f"{raw_flux:.2f}", HUD_TEXT, raw_flux, 3.5, (70, 160, 255))
    row("SOLAR FLUX  FILTERED", f"{flt_flux:.2f}", HUD_TEXT, flt_flux, 3.5, (255, 195, 50))
    row("TEMPERATURE", f"{temperature:.3f}", (255, 120, 70), temperature, 1.0, (255, 100, 50))
    row("BEAM CURRENT (PID)", f"{beam_current:.3f} A", (160, 120, 255), beam_current, 1.0, (150, 100, 255))
    row("CYCLOTRON POWER", f"{cyclotron_watts / 1000:.2f} kW", (120, 220, 255), cyclotron_watts, 5000.0,
        (100, 200, 255))
    row("CAPACITOR CHARGE", f"{cap_charge:.1f} %", (255, 210, 60), cap_charge, 100.0, (255, 200, 40))
    row("RF SYNC", f"{rf_sync * 100:.1f} %",
        (80, 255, 140) if rf_sync > 0.8 else (255, 100, 60),
        rf_sync, 1.0,
        (80, 255, 140) if rf_sync > 0.8 else (255, 80, 40))
    row("PARTICLES", f"{count}", HUD_TEXT)
    row("SIM TIME", f"{sim_t:.1f} s", HUD_TEXT)
    row("DELTA-T", f"{dt_ms:.0f} ms", HUD_TEXT)


# ─── ÇİZİM: SAĞ PANEL ────────────────────────────────────────────────────────
def draw_badge(surf, font, font_s, state, sim_time):
    cfg = STATE_CFG[state]
    col = list(cfg[1])
    label = cfg[0]

    if state == State.CRITICAL_FAILURE and int(sim_time * 3) % 2 == 0:
        col = [255, 80, 80]

    txt = font.render(f"●  {label}", True, tuple(col))
    w = max(txt.get_width() + 28, 180)
    h = txt.get_height() + 14
    bg = pygame.Surface((w, h), pygame.SRCALPHA)
    bg.fill((0, 18, 38, 185))
    pygame.draw.rect(bg, (*col, 70), (0, 0, w, h), 1)

    if state in (State.OVERDRIVE, State.CRITICAL_FAILURE) and random.random() < 0.1:
        gx, gy = random.randint(-2, 2), random.randint(-2, 2)
        surf.blit(bg, (WIDTH - w - 16 + gx, 16 + gy))
        surf.blit(txt, (WIDTH - w - 4 + gx, 23 + gy))
    else:
        surf.blit(bg, (WIDTH - w - 16, 16))
        surf.blit(txt, (WIDTH - w - 4, 23))

    desc = font_s.render(STATE_DESCRIPTIONS[state], True, tuple(col))
    surf.blit(desc, (WIDTH - w - 16, 16 + h + 4))


# ─── ÇİZİM: GRAFIKLER ────────────────────────────────────────────────────────
def draw_flux_graph(surf, font_s, data, gx, gy, gw, gh):
    bg = pygame.Surface((gw, gh), pygame.SRCALPHA)
    bg.fill((0, 12, 30, 165))
    pygame.draw.rect(bg, (70, 160, 240, 40), (0, 0, gw, gh), 1)
    surf.blit(bg, (gx, gy))
    if len(data) < 2: return
    step = gw / max(len(data), 1)
    mx = 3.5

    def plot(key, col, lw):
        pts = [(gx + int(i * step), gy + gh - int((d[key] / mx) * (gh - 6)) - 3)
               for i, d in enumerate(data)]
        if len(pts) >= 2:
            pygame.draw.lines(surf, col, False, pts, lw)

    plot("raw", (70, 155, 255), 1)
    plot("flt", (255, 195, 50), 2)
    surf.blit(font_s.render("RAW", True, (70, 155, 255)), (gx + 5, gy + 4))
    surf.blit(font_s.render("FILTERED", True, (255, 195, 50)), (gx + 5, gy + 16))


def draw_temp_graph(surf, font_s, temp_hist, gx, gy, gw, gh):
    bg = pygame.Surface((gw, gh), pygame.SRCALPHA)
    bg.fill((0, 12, 30, 165))
    pygame.draw.rect(bg, (70, 160, 240, 40), (0, 0, gw, gh), 1)
    surf.blit(bg, (gx, gy))

    thresh_y = gy + gh - int(CRITICAL_TEMP * (gh - 6)) - 3
    pygame.draw.line(surf, (255, 60, 40, 180), (gx + 2, thresh_y), (gx + gw - 2, thresh_y), 1)
    surf.blit(font_s.render("CRITICAL", True, (255, 80, 60)), (gx + 5, thresh_y - 14))

    if len(temp_hist) < 2: return
    step = gw / max(len(temp_hist), 1)
    pts = [(gx + int(i * step), gy + gh - int((t) * (gh - 6)) - 3)
           for i, t in enumerate(temp_hist)]
    if len(pts) >= 2:
        pygame.draw.lines(surf, (255, 120, 60), False, pts, 2)
    surf.blit(font_s.render("TEMPERATURE", True, (255, 120, 60)), (gx + 5, gy + 4))


def draw_pid_graph(surf, font_s, pid_hist, gx, gy, gw, gh):
    bg = pygame.Surface((gw, gh), pygame.SRCALPHA)
    bg.fill((0, 12, 30, 165))
    pygame.draw.rect(bg, (70, 160, 240, 40), (0, 0, gw, gh), 1)
    surf.blit(bg, (gx, gy))
    if len(pid_hist) < 2: return
    step = gw / max(len(pid_hist), 1)
    pts = [(gx + int(i * step), gy + gh - int(v * (gh - 6)) - 3)
           for i, v in enumerate(pid_hist)]
    if len(pts) >= 2:
        pygame.draw.lines(surf, (160, 100, 255), False, pts, 2)
    surf.blit(font_s.render("BEAM CURRENT (PID)", True, (160, 100, 255)), (gx + 5, gy + 4))


# ─── STATE TRANSITION ────────────────────────────────────────────────────────
def next_state(current, flt_flux, temperature):
    if current == State.CRITICAL_FAILURE:
        return State.RECOVERY_MODE if temperature <= RECOVERY_TEMP else State.CRITICAL_FAILURE
    if current == State.RECOVERY_MODE:
        return State.IDLE if temperature <= 0.05 else State.RECOVERY_MODE
    if current == State.OVERDRIVE and temperature >= CRITICAL_TEMP:
        return State.CRITICAL_FAILURE
    for s, (lo, hi) in FLUX_THRESHOLDS.items():
        if lo <= flt_flux < hi:
            return s
    return current


# ─── ANA DÖNGÜ ───────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(
        "HELIOS Shield System — Phase 4: Visual Polish & Presentation Mode")
    clock = pygame.time.Clock()

    font = get_font(15, bold=True)
    font_s = get_font(11)

    stars = [Star() for _ in range(220)]
    particles = []
    impacts = []
    cme_bursts = []
    flux_samples = deque(maxlen=MA_WINDOW * 4)
    graph_data = deque(maxlen=200)
    temp_hist = deque(maxlen=200)
    pid_hist = deque(maxlen=200)

    pid = PIDController(kp=0.55, ki=0.08, kd=0.12)

    accumulator = 0.0
    sim_time = 0.0
    spawn_accum = 0.0
    raw_flux = 1.5
    flt_flux = 1.5
    temperature = 0.0
    beam_current = 0.0
    cyclotron_watts = 0.0
    rf_sync = 1.0
    cap_charge = 0.0
    shield_alpha = 40.0
    state = State.IDLE
    cme_timer = random.uniform(20.0, 35.0)
    manual_flux = None   # None = otomatik mod, float = manuel override

    show_ui = True
    jury_mode = False

    prev_ticks = pygame.time.get_ticks()

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit();
                sys.exit()
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    pygame.quit();
                    sys.exit()
                if ev.key == pygame.K_1: manual_flux = 0.8
                if ev.key == pygame.K_2: manual_flux = 1.5
                if ev.key == pygame.K_3: manual_flux = 2.1
                if ev.key == pygame.K_4: manual_flux = 2.8
                if ev.key == pygame.K_0: manual_flux = None   # otomatik moda dön
                if ev.key == pygame.K_h: show_ui = not show_ui
                if ev.key == pygame.K_j: jury_mode = not jury_mode

        now = pygame.time.get_ticks()
        frame_dt = min((now - prev_ticks) / 1000.0, 0.05)
        prev_ticks = now
        accumulator += frame_dt

        # ── Fizik (200 Hz fixed timestep) ────────────────────────────────────
        while accumulator >= PHYS_DT:
            sim_time += PHYS_DT

            if manual_flux is not None:
                # Manuel override aktif — CME zamanlayıcısı beklemede tutulur
                # ki override'dan çıkınca aniden eski bir CME tetiklenmesin.
                raw_flux = manual_flux
                cme_timer = random.uniform(20.0, 40.0)
            else:
                cme_timer -= PHYS_DT
                if cme_timer <= 0:
                    raw_flux = random.uniform(3.0, 4.0)
                    cme_timer = random.uniform(20.0, 40.0)
                    cme_bursts.append(CMEBurst(SUN_X, SUN_Y))
                    for _ in range(40):
                        if len(particles) >= MAX_PARTICLES:
                            break
                        particles.append(Particle(flux_mult=1.5, is_cme=True))
                else:
                    raw_flux = max(0.1,
                                   1.5
                                   + noise(sim_time, 0.4, 0.6)
                                   + noise(sim_time, 1.8, 0.3)
                                   + random.uniform(0, 0.35))

            flux_samples.append(raw_flux)
            flt_flux = moving_average(flux_samples, MA_WINDOW)
            graph_data.append({"raw": raw_flux, "flt": flt_flux})

            if state in (State.CRITICAL_FAILURE, State.RECOVERY_MODE):
                pid.reset()
                beam_current = 0.0
            else:
                setpoint = min(1.0, flt_flux / 3.5)
                beam_current = pid.update(setpoint, temperature * 0.4, PHYS_DT)

            pid_hist.append(beam_current)

            if state == State.STORM_ALERT:
                cap_charge = min(CAP_MAX, cap_charge + PHYS_DT * 18.0)
            elif state == State.OVERDRIVE:
                cap_charge = max(0.0, cap_charge - PHYS_DT * 35.0)
            elif state in (State.IDLE, State.LOW_THREAT):
                cap_charge = max(0.0, cap_charge - PHYS_DT * 5.0)

            base_power = beam_current * 3000.0
            cap_bonus = (cap_charge / 100.0) * 2000.0 if state == State.OVERDRIVE else 0.0
            cyclotron_watts = base_power + cap_bonus

            if state == State.OVERDRIVE:
                heat_in = PHYS_DT * flt_flux * 0.18 * (1.0 + beam_current * 0.5)
                heat_out = PHYS_DT * 0.04
                temperature += heat_in - heat_out
            elif state in (State.CRITICAL_FAILURE, State.RECOVERY_MODE):
                temperature = max(0.0, temperature - PHYS_DT * 0.12)
            else:
                temperature = max(0.0, temperature - PHYS_DT * 0.05)

            temp_hist.append(min(temperature, 1.2))

            if state == State.CRITICAL_FAILURE:
                rf_sync = max(0.0, rf_sync - PHYS_DT * 0.8)
            elif state == State.RECOVERY_MODE:
                rf_sync = min(1.0, rf_sync + PHYS_DT * 0.3)
            else:
                rf_sync = min(1.0, rf_sync + PHYS_DT * 0.5)

            state = next_state(state, flt_flux, temperature)

            flux_mult = {
                State.IDLE: 0.15, State.LOW_THREAT: 0.3,
                State.STORM_ALERT: 0.55, State.OVERDRIVE: 1.0,
                State.CRITICAL_FAILURE: 1.2, State.RECOVERY_MODE: 0.2
            }.get(state, 0.3)

            spawn_accum += flt_flux * flux_mult
            while spawn_accum >= 1.0 and len(particles) < MAX_PARTICLES:
                particles.append(Particle(flux_mult))
                spawn_accum -= 1.0

            shield_r = MARS_R + 28
            nxt = []
            for p in particles:
                p.try_deflect(shield_r, state, beam_current)
                p.update()
                if p.hits_mars():
                    # Kalkanın saptırmadığı (IDLE dahil) her çarpma görünür
                    # olmalı — daha önce IDLE'da parçacıklar flaşsız,
                    # sanki kalkan tutmuş gibi sessizce kayboluyordu.
                    impacts.append(ImpactFlash(p.x, p.y))
                elif p.alive():
                    nxt.append(p)
            particles = nxt
            impacts = [f for f in impacts if (f.update() or True) and f.alive()]

            for b in cme_bursts:
                b.update()
            cme_bursts = [b for b in cme_bursts if b.active]

            accumulator -= PHYS_DT

        # DIKKAT: Hatanın düzeltildiği yer burası (Endeks 3 yerine 2 yapıldı)
        target_alpha = float(STATE_CFG[state][2])
        shield_alpha += (target_alpha - shield_alpha) * 0.06

        # ── RENDER (60 FPS) ───────────────────────────────────────────────────
        screen.fill(BG_COLOR)

        if jury_mode:
            draw_tactical_grid(screen, font_s, beam_current)

        for s in stars:     s.draw(screen)
        draw_sun(screen, state, sim_time)
        for b in cme_bursts: b.draw(screen)

        draw_shield_aurora(screen, state, sim_time, shield_alpha, beam_current, temperature)

        for p in particles: p.draw(screen)
        for f in impacts:   f.draw(screen)
        draw_mars(screen, font_s, state, show_ui)

        if show_ui:
            draw_hud_left(screen, font, font_s,
                          raw_flux, flt_flux, temperature,
                          beam_current, cyclotron_watts, rf_sync,
                          cap_charge, len(particles), sim_time, frame_dt * 1000)

            draw_badge(screen, font, font_s, state, sim_time)

            draw_flux_graph(screen, font_s, graph_data, 16, HEIGHT - 78, 340, 60)
            draw_temp_graph(screen, font_s, temp_hist, 16 + 340 + 8, HEIGHT - 78, 280, 60)
            draw_pid_graph(screen, font_s, pid_hist, 16 + 340 + 8 + 280 + 8, HEIGHT - 78, 260, 60)

            hint = font_s.render(
                "1-4: MANUAL FLUX  0: AUTO  |  H: TOGGLE HUD  |  J: TACTICAL GRID  |  ESC:QUIT",
                True, (55, 95, 155))
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 18))

        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()