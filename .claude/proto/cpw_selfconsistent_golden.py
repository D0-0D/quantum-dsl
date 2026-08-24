# N10 新 golden: 自洽 CPW 集总 (Göppl Eq.2-5 + Simons sinh + Mohebbi-Majedi Lk)
import math

C0 = 299792458.0
MU0 = 4 * math.pi * 1e-7
EPS0 = 1.0 / (MU0 * C0 * C0)


def ellipk(m):
    a, b = 1.0, math.sqrt(1.0 - m)
    for _ in range(64):
        if abs(a - b) <= 1e-17 * a:
            break
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return math.pi / (2.0 * a)


def cpw(freq, s, w, h, t, eps_r=11.45, tand=1e-5, lam_l=30e-9):
    k0 = s / (s + 2 * w)
    k01 = math.sqrt(1 - k0**2)
    k1 = math.sinh(math.pi * s / (4 * h)) / math.sinh(math.pi * (s + 2 * w) / (4 * h))
    k11 = math.sqrt(1 - k1**2)
    Kk0, Kk01, Kk1, Kk11 = (ellipk(k0**2), ellipk(k01**2),
                            ellipk(k1**2), ellipk(k11**2))
    q = 0.5 * (Kk1 * Kk01) / (Kk11 * Kk0)
    eps_eff = 1 + q * (eps_r - 1)
    C = 2 * EPS0 * (eps_r - 1) * (Kk1 / Kk11) + 4 * EPS0 * (Kk0 / Kk01)
    assert abs(C - 4 * EPS0 * eps_eff * Kk0 / Kk01) < 1e-25  # 同一式两写法
    Lg = MU0 / 4 * Kk01 / Kk0
    # Lk (Mohebbi & Majedi) — 与参考实现逐行相同
    A1 = (-t / math.pi) + 0.5 * math.sqrt((2 * t / math.pi) ** 2 + s**2)
    B1 = s**2 / (4 * A1)
    C1 = B1 - (t / math.pi) + math.sqrt((t / math.pi) ** 2 + w**2)
    D1 = 2 * t / math.pi + C1
    LkS = MU0 * lam_l * C1 / (4 * A1 * D1 * Kk0)
    Lk = (LkS * 1.7 / math.sinh(t / (2 * lam_l))
          + LkS * 0.4 / math.sqrt((((B1 / A1) ** 2) - 1) * (1 - (B1 / D1) ** 2)))
    Ltot = Lg + Lk
    Z0 = math.sqrt(Ltot / C)
    lam_g = 1.0 / (freq * math.sqrt(Ltot * C))
    G = 2 * math.pi * freq * C * q * tand
    return dict(Lk=Lk, Lext=Lg, C=C, G=G, Z0=Z0, eps_eff=eps_eff, q=q,
                lambda_g=lam_g)


typ = cpw(5e9, 10e-6, 6e-6, 760e-6, 200e-9)
for k, v in typ.items():
    print(f"{k} = {v!r}")

OLD = dict(Lk=2.3681287381377575e-09, Lext=4.353629666360981e-07,
           C=1.63492916307188e-10, Z0=51.60315696321091,
           eps_eff=6.065432087076736, lambda_g=0.024345363624151843)
print("\n相对旧参考值:")
for k, old in OLD.items():
    print(f"{k}: {(typ[k]/old - 1)*100:+.3f}%")

# 一致性: 无 Lk 时 Z0·vp 应回到共形映射闭式 Z0 = 1/(vp·C)
noLk = math.sqrt(cpw(5e9, 10e-6, 6e-6, 760e-6, 200e-9)["Lext"] / typ["C"])
print(f"\nZ0(不含Lk) = {noLk!r}  → Lk 抬升 {(typ['Z0']/noLk-1)*100:+.3f}%")

# 窄线用例 (test_kinetic_inductance_can_dominate) 仍需 Lk > Lext
narrow = cpw(5e9, 1e-6, 0.5e-6, 500e-6, 20e-9, lam_l=90e-9)
print(f"\n窄线: Lk={narrow['Lk']:.4e}  Lext={narrow['Lext']:.4e}  "
      f"Lk>Lext: {narrow['Lk'] > narrow['Lext']}")
