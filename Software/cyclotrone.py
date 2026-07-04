import pygame
import sys
import math
from collections import deque

# ─── EKRAN VE RENKLER ────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 720
FPS = 60
BG_COLOR = (10, 15, 25)
DEE_COLOR = (40, 80, 120)
DEE_EDGE = (70, 150, 220)
PARTICLE_COLOR = (255, 100, 50)
TRAIL_COLOR = (255, 150, 80)
TEXT_COLOR = (150, 200, 255)

# ─── FİZİK PARAMETRELERİ (Siklotron Kalbi) ──────────────────────────────────
# Gerçek proton sabitleri (SI) — HUD'daki Tesla/MHz/MeV etiketlerinin
# gerçek fizikle örtüşmesi için normalize edilmiş Q=M=1 yerine kullanılıyor.
Q_PROTON = 1.602176634e-19     # proton yükü (Coulomb)
M_PROTON = 1.67262192369e-27   # proton kütlesi (kg)
QM_RATIO = Q_PROTON / M_PROTON  # ≈ 9.5788e7 C/kg — proton yük/kütle oranı
JOULE_TO_MEV = 1.0 / 1.602176634e-13

R_MAX = 300.0  # Dee plakalarının yarıçapı (cm)
GAP = 30.0  # İki Dee arasındaki boşluk (cm) (Elektrik alanın olduğu yer)
CM_TO_M = 0.01

# Ekrandaki sarmalın insan gözüyle takip edilebilmesi için animasyon,
# gerçek zamana göre yavaşlatılmıştır. Bu SADECE görsel oynatma hızını etkiler;
# RF FREKANSI ve KİNETİK ENERJİ değerleri gerçek proton fiziğinden hesaplanır.
# TIME_DILATION = proton yük/kütle oranı seçildiği için görsel davranış,
# eski normalize edilmiş (Q=M=1) sürümle birebir aynı kalır.
TIME_DILATION = QM_RATIO  # ≈ 1:95,788,000 gerçek zaman


class CyclotronSimulation:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("HELIOS - Cyclotron Core Engineering Lab")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Consolas", 14, bold=True)
        self.font_large = pygame.font.SysFont("Consolas", 24, bold=True)

        # Kontrol Edilebilir Parametreler
        self.B_field = 1.5  # Manyetik Alan (Tesla)
        self.E_max = 200.0  # Maksimum Hızlandırma Voltajı (kV eşdeğeri)

        # Parçacık Durumu
        self.reset_particle()
        self.sim_time = 0.0
        self.dt = 1.0 / 1000.0  # Hassas fizik adımı (1 ms)

    def reset_particle(self):
        # Merkeze çok yakın bir noktadan sıfıra yakın hızla başlatıyoruz
        self.x = 0.1
        self.y = 1.0
        self.vx = 0.0
        self.vy = 10.0
        self.trail = deque(maxlen=600)
        self.is_active = False
        self.energy_mev = 0.0
        self.sim_time = 0.0

    def physics_step(self):
        if not self.is_active:
            return

        # Gerçek proton siklotron açısal frekansı (w = qB/m), yavaşlatılmış
        # (görsel) zaman ölçeğine indirgenmiş hali. TIME_DILATION = QM_RATIO
        # olduğu için omega_visual sayısal olarak B_field'a eşittir —
        # yani sarmalın ekrandaki görünümü değişmez, sadece artık gerçek
        # fizikten türetilmiştir.
        omega_visual = (QM_RATIO * self.B_field) / TIME_DILATION

        # RF Voltajı (Zamanla yön değiştiren AC elektrik alanı)
        # Sadece GAP (boşluk) içindeyken etki eder
        current_E = self.E_max * math.cos(omega_visual * self.sim_time)

        # 1. ELEKTRİK ALAN (Sadece x eksenindeki boşlukta)
        # E_max/GAP burada gerçek bir alan şiddeti değil, görsel hızlanma
        # oranını ayarlayan bir sürükleme parametresidir.
        if abs(self.x) < GAP / 2.0:
            ax = current_E
            self.vx += ax * self.dt
            # Boşlukta manyetik alan zayıftır (idealleştirilmiş model)
        else:
            # 2. MANYETİK ALAN (Dee'lerin içinde Dairesel Hareket)
            # Lorentz Kuvveti: v' = Rotasyon Matrisi (Tam kararlı dairesel yörünge için)
            theta = omega_visual * self.dt
            new_vx = self.vx * math.cos(theta) + self.vy * math.sin(theta)
            new_vy = -self.vx * math.sin(theta) + self.vy * math.cos(theta)
            self.vx = new_vx
            self.vy = new_vy

        # Konum güncelleme
        self.x += self.vx * self.dt
        self.y += self.vy * self.dt
        self.sim_time += self.dt

        # Kinetik Enerji — GERÇEK proton fiziği: klasik siklotron
        # enerji-yarıçap ilişkisi KE = (qBr)^2 / (2m), r = merkeze uzaklık (m)
        r_sim = math.hypot(self.x, self.y)
        r_m   = r_sim * CM_TO_M
        ke_joules = (Q_PROTON * self.B_field * r_m) ** 2 / (2 * M_PROTON)
        self.energy_mev = ke_joules * JOULE_TO_MEV

        # Trail'e ekle (Çizim için performans optimizasyonu: her 5 adımda 1 ekle)
        if int(self.sim_time / self.dt) % 5 == 0:
            self.trail.append((self.x, self.y))

        # Siklotrondan çıkış veya duvara çarpma kontrolü
        if r_sim > R_MAX:
            self.is_active = False  # Parçacık başarıyla fırlatıldı!

    def draw_dees(self):
        cx, cy = WIDTH // 2, HEIGHT // 2

        # Sol Dee (D şeklinde metal plaka)
        left_rect = pygame.Rect(cx - R_MAX - GAP // 2, cy - R_MAX, R_MAX * 2, R_MAX * 2)
        pygame.draw.arc(self.screen, DEE_EDGE, left_rect, math.pi / 2, 3 * math.pi / 2, 4)
        pygame.draw.line(self.screen, DEE_EDGE, (cx - GAP // 2, cy - R_MAX), (cx - GAP // 2, cy + R_MAX), 4)

        # Sağ Dee
        right_rect = pygame.Rect(cx - R_MAX + GAP // 2, cy - R_MAX, R_MAX * 2, R_MAX * 2)
        pygame.draw.arc(self.screen, DEE_EDGE, right_rect, -math.pi / 2, math.pi / 2, 4)
        pygame.draw.line(self.screen, DEE_EDGE, (cx + GAP // 2, cy - R_MAX), (cx + GAP // 2, cy + R_MAX), 4)

        # Merkez (İyon Kaynağı)
        pygame.draw.circle(self.screen, (255, 255, 255), (cx, cy), 6)

    def draw_particle(self):
        cx, cy = WIDTH // 2, HEIGHT // 2

        # Trail çizimi (Sarmal izi)
        if len(self.trail) > 1:
            pts = [(cx + tx, cy - ty) for (tx, ty) in self.trail]
            pygame.draw.lines(self.screen, TRAIL_COLOR, False, pts, 2)

        # Parçacığın kendisi
        if self.is_active:
            px, py = int(cx + self.x), int(cy - self.y)
            pygame.draw.circle(self.screen, PARTICLE_COLOR, (px, py), 5)
            # Parlama efekti
            s = pygame.Surface((20, 20), pygame.SRCALPHA)
            pygame.draw.circle(s, (*PARTICLE_COLOR, 100), (10, 10), 10)
            self.screen.blit(s, (px - 10, py - 10))

    def draw_hud(self):
        real_freq_mhz = (QM_RATIO * self.B_field) / (2 * math.pi) / 1e6
        texts = [
            f"MAGNETIC FIELD (B): {self.B_field:.2f} Tesla  [UP/DOWN to adjust]",
            f"RF VOLTAGE (E):     {self.E_max:.0f} kV     [LEFT/RIGHT to adjust]",
            f"RF FREQUENCY:       {real_freq_mhz:.3f} MHz (Auto-Tuned, real proton)",
            f"SIM SPEED:          1 : {TIME_DILATION:,.0f}  (slow-motion playback)",
            "",
            f"CURRENT RADIUS:     {math.hypot(self.x, self.y):.1f} cm",
            f"KINETIC ENERGY:     {self.energy_mev:.2f} MeV"
        ]

        for i, text in enumerate(texts):
            col = (255, 200, 100) if "ENERGY" in text else TEXT_COLOR
            surf = self.font.render(text, True, col)
            self.screen.blit(surf, (20, 20 + i * 25))

        # Fırlatma Uyarısı
        if not self.is_active and self.energy_mev == 0:
            warn = self.font_large.render("PRESS [SPACE] TO INJECT ION", True, (100, 255, 100))
            self.screen.blit(warn, (WIDTH // 2 - warn.get_width() // 2, HEIGHT - 50))
        elif not self.is_active and self.energy_mev > 0:
            warn = self.font_large.render("PARTICLE EJECTED! PRESS [SPACE] TO RESTART", True, (255, 100, 100))
            self.screen.blit(warn, (WIDTH // 2 - warn.get_width() // 2, HEIGHT - 50))

    def run(self):
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self.reset_particle()
                        self.is_active = True
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()

            # Klavye Kontrolleri (Basılı tutma)
            keys = pygame.key.get_pressed()
            if keys[pygame.K_UP]:   self.B_field = min(5.0, self.B_field + 0.02)
            if keys[pygame.K_DOWN]: self.B_field = max(0.1, self.B_field - 0.02)
            if keys[pygame.K_RIGHT]: self.E_max = min(1000.0, self.E_max + 5.0)
            if keys[pygame.K_LEFT]:  self.E_max = max(10.0, self.E_max - 5.0)

            # Fizik Motoru (1 Karede 20 alt-adım atarak kusursuz sarmal sağlarız)
            for _ in range(20):
                self.physics_step()

            # Çizimler
            self.screen.fill(BG_COLOR)

            # Arka Plan Izgarası
            for x in range(0, WIDTH, 50):
                pygame.draw.line(self.screen, (20, 30, 40), (x, 0), (x, HEIGHT))
            for y in range(0, HEIGHT, 50):
                pygame.draw.line(self.screen, (20, 30, 40), (0, y), (WIDTH, y))

            self.draw_dees()
            self.draw_particle()
            self.draw_hud()

            pygame.display.flip()
            self.clock.tick(FPS)


if __name__ == "__main__":
    CyclotronSimulation().run()