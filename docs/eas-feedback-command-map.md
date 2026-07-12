# EAS Feedback 필드 라벨 → 드라이브 명령 매핑 (cmdmap/fable-reader 2026-07-12)

`feedback_spec.py` 인코딩용. 확신도 S=강, M=중, 미확정=문서 공백. UI 구조는 `eas-feedback-panels.md`.

## 소켓 인덱싱 규칙 (기반)
소켓 s(1~4): 센서 ID=`CA[40+s]` · Direction=`CA[53+s]` · Velocity FIR 점수=`CA[70+s]` · FIR 타입=`CA[74+s]` · Absolute Position Offset=`CA[90+s]`. **이 드라이브 s=1** (CA[41]=30 실측). 그 외 CA[]는 소켓 공용.

## 매핑표 (라벨 → 명령)
| EAS 라벨 | 명령 | Access/형 | 값 대응·변환 | 확신 |
|---|---|---|---|---|
| Direction | CA[53+s] (CA[54~57]) | RW enum | 0=Non Invert, 1=Invert | S |
| Glitch Filter (cnt/sec 또는 Cycles/sec) | CA[50](Port B)/CA[51](Port A) | RW int | counts/s. **포트 기준** | S |
| Input Glitch Filter (nanosecond) | CA[35] | RW int 2~255 | **ns=(CA[35]+1)×13.333**; EAS enum 40..360/40 ↔ CA[35]=3n−1 (40↔2,120↔8,240↔17) | S |
| Clock Frequency (MHz) | CA[36] | RW enum | CR {6.25M/12.5M/25M Hz} ↔ EAS {1.250/2.500/5.000}. **스케일 미확정(원시값 병기)** | S동정/미확정스케일 |
| HW Sensor Resolution (Bits) | CA[59] (Gurley=CA[21] 10~12) | RW int 1~32 | 싱글턴 비트. 실측 19 | S |
| SW Sensor Resolution (Bits) | CA[61] 역산 | RW int | **CA[61]=CA[59]−SW−CA[58]** (실측 19−16−0→3) | S |
| High Bits Mask (Bits) | CA[58] | RW int 0~8 | EAS dd 0..8 일치 | S |
| Rotary Multi-turn Resolution | CA[62] | RW int 0~16 | Panasonic{0,16}. 실측 16 | S |
| Error Bitwise Mask (0x…) | CA[8] | RW bitmask | −1=전부 마스크. 0x는 표시형식 | M~S |
| Error Bit Mask (False/True) | CA[8] (0/1) | RW bool | "무시" 극성 미검증 → live-diff | M |
| Error Bit Number | CA[22] | RW int −1~29 | −1=없음 | S |
| Position LSB number | CA[67] | RW int 0~56 | SSI | S |
| Protocol Total Bits | CA[66] | RW int 0~64 | SSI | S |
| First Clock Delay (µs) | CA[86] | RW int 0~15 | **µs=CA[86]×0.4** (16옵션 일치) | S |
| Velocity FIR Filter Window | CA[70+s] 점수 + CA[74+s] 타입 | RW int/bool | Disabled↔점수0/타입0(**이중후보 live-diff**), 2..8↔점수 | S동정/미확정 |
| Multiplication Factor | CA[31] | RW int 2~16 | counts/cycle=2^CA[31], 기본10 | S |
| Resolver Pole Pairs | CA[32] | RW int | 기본1 | S |
| Resolver Frequency [kHz] | CA[34] | RW enum{0,1,2,4} | {10,5,2.5,1.2}kHz↔{0,1,2,4} | S(가정1) |
| Temperature Support [BiSS] | CA[60] bit0 | RW bool | 0/1 | S |
| Warning Report [BiSS Gen] | CA[60] bit10 | RW bool | | M~S |
| Read EnDat External Temperature | CA[60] bit0 | RW bool | **FW 01.01.16.10>이 드라이브 — 쓰기 실패 예상 처리** | M+FW경고 |
| Use Digital Halls | CA[20] | RW enum | 0=No,1=Yes | S |
| Signal Type | AR[1] | RW int 1~3 | 1=Current,2=Velocity,3=Position | S |
| Analog Offset | AS[1] | RW Float | | M~S |
| Neg/Pos Dead-Band | AD[1]/AD[2] | RW Float V | | S |
| Gain (A/V) | AG[1] | RW Float | | S |
| Encoder Maintenance (btn) | TW[18](ST리셋)·TW[19](MT리셋)·TW[20]=s(에러클리어) | Write-only | 오설정시 EC=99 | M |

## Resolution 그룹 (파생 ro — 표시만, 쓰기 대상 아님)
- counts/revolution = CA[18] (rotary). 시리얼=2^SW · **Halls=6×CA[19]**(96=6×16) · Tamagawa=2^14.
- cycles/revolution = CA[18]/2^CA[31] (아날로그). lines/revolution = CA[18]/4 (쿼드).

## 미확정 (표시전용으로, live-diff 후 확정)
Serial Data Polling · Communication Time (µs) · BiSS Mode(C-Mode) · Resolution Type(Binary) · Sensor Data Presentation(Binary) · Hiperface serial status polling.

## 인코딩 규율 (필수)
1. **쓰기 게이트**: 위 CA 전부 **MO=0**; 커뮤 소켓 관련은 커뮤 리셋 동반; 영속화 **SV**(MO=0). CA[35]/CA[36] 변경 후 CA[41~44] 재기입.
2. **변환식 3건 내장**: Glitch ns↔CA[35] `(v+1)×13.333`, SW Res↔CA[61] `CA[59]−SW−CA[58]`, First Clock Delay↔CA[86] `×0.4`. Clock 스케일은 원시값+양해석 병기.
3. **미확정 필드 = read-only 표시("미확정" 태그)**, 쓰기 금지.
4. **EnDat 2.2 실기 오라클 스냅숏**: CA[41]=30, CA[59]=19, CA[61]=3, CA[58]=0, CA[62]=16, CA[35]=8, CA[18]=65536 — 첫 라이브 read 대조로 매핑 전체 검정.
