# EAS III Feedback Settings — per-sensor panel spec (from video, fable-vision 2026-07-12)

정본. 클론의 동적 Feedback 패널을 EAS와 똑같이 미러링하기 위한 화면 구조. 프레임 앵커 = `media/fb_keyframes/f_NNNN.png`.
표기: dd=드롭다운(옵션), dd?=드롭다운이나 옵션 미확인(고정 가능), v=값, ro=읽기전용(회색/파생), btn=버튼.

## 공통 화면 구조
- 상단: `Feedback on Motor` + Position(v-ro) → **센서 타입 콤보**(정본 이름 아래 목록). 우측 `Feedback on Load` = None.
- 그리드 그룹: **General** → **Sensor Parameters** → (일부) **Serial Encoder Frame**([∞] 팝업 버튼) → **Resolution**(파생 ro) → **Advanced**(접힘).
- General 공통: Sensor Name(ro) / Sensor Type=`Rotary`(ro) / Feedback Control Function=`Position + Velocity + Commutation`(ro) / (일부) Use Digital Halls(dd No/Yes).
- 노랑 배경 = 미입력(0)/invalid. 대부분 센서 마지막 필드 = Velocity FIR Filter Window(dd: Disabled,2..8).

## 센서 타입 콤보 — 정본 이름 (verbatim, Port 표기 포함)
Analog Input #1, Port C · Analog Sin/Cos, Port B · Encoder Quad, Port B · Halls Only, Port A ·
Pulse and Direction, Port A · Pulse and Direction, Port B · Quad Exclusive 1, Port A · Resolver, Port B ·
Serial - Panasonic Incremental, Port A · Serial Absolute - BiSS General, Port A · Serial Absolute - BiSS, Port A ·
Serial Absolute - EnDat 2.1 designation 22, Port A · Serial Absolute - EnDat 2.2 designation 22, Port A ·
Serial Absolute - Hiperface, Port A and B · Serial Absolute - IAI, Port A · Serial Absolute - Kawasaki, Port A ·
Serial Absolute - Mitsubishi, Port A · Serial Absolute - Panasonic, Port A · Serial Absolute - Sanyo / Nikon, Port A ·
Serial Absolute - SSI, Port A · Serial Absolute - Tamagawa, Port A · Serial Exclusive #3 · Virtual Absolute - Gurley, Port B

## 센서별 Sensor Parameters 필드 (General 3~4행 공통은 생략, 각 센서 고유부만)

- **Analog Input #1** (f2): Use Digital Halls(dd) · Direction(dd) · Signal Type(dd: Current/Velocity/Position) · Analog Offset(v) · Neg Dead-Band(v) · Pos Dead-Band(v) · Gain A/V(v) · Velocity FIR(dd) · [Analog Input Filter] Filter Type(dd) · Res: counts/rev(노랑)
- **Analog Sin/Cos** (f5): Direction(dd) · Multiplication Factor(dd) · Glitch Filter (Cycles/sec)(v) · Absolute Position Offset(v) · Velocity FIR(dd) · Res: cycles/rev(노랑) counts/rev(ro)
- **Encoder Quad** (f7): Direction(dd) · Glitch Filter (cnt/sec)(v) · Velocity FIR(dd) · Res: lines/rev(노랑) counts/rev(노랑)
- **Halls Only** (f9): Velocity FIR(dd) 단일 · Res: counts/rev=96(v). (Use Digital Halls 없음, General 3행)
- **Pulse and Direction A/B** (f11/f13): Use Digital Halls(dd) · Direction(dd) · Glitch Filter (nanosecond)(v) · Velocity FIR(dd) · Res: counts/rev(노랑)
- **Quad Exclusive 1** (f15): Use Digital Halls=Yes(dd) · Direction(dd) · Glitch Filter (cnt/sec)(v) · Velocity FIR(dd) · Res: lines/rev, counts/rev(노랑)
- **Resolver** (f17/18): Direction(dd) · Resolver Pole Pairs(v) · Multiplication Factor(dd) · Resolver Frequency [kHz](dd: 10/5/2.5/1.2) · Absolute Position Offset(v) · Velocity FIR(dd) · Res: cycles/rev(ro) counts/rev(ro)
- **Serial - Panasonic Incremental** (f21/24): Direction(dd) · HW Sensor Resolution (Bits)(dd) · SW Sensor Resolution (Bits)(dd) · Clock Frequency (MHz)(dd,ro라벨) · Input Glitch Filter (nanosecond)(dd: 40..360/40) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time (microsecond)(v) · Encoder Maintenance(btn Open) · Velocity FIR(dd) · Res: counts/rev(ro)
- **BiSS General** (f27/30/33): Direction(dd) · Resolution Type=Binary(dd) · BiSS Mode=C-Mode(dd) · Clock Frequency (MHz)(dd) · Input Glitch Filter (ns)(dd) · Serial Data Polling(dd) · Error Bit Mask(dd False/True) · Warning Report(dd) · Communication Time (us)(v) · Absolute Position Offset(v) · Velocity FIR(dd) · **[Serial Encoder Frame]**: HW Res Bits(v) SW Res Bits(dd) Rotary Multi-turn Res(v) High Bits Mask(dd) Position LSB number(v) Error Bit Number(dd) Protocol Total Bits(v) · Res: counts/rev(ro)
- **BiSS** (f36): Direction(dd) · Temperature Support(dd) · Clock Frequency (MHz)(dd:1.25/2.5/5.0) · Input Glitch(dd) · Serial Data Polling(dd) · Error Bit Mask(dd) · Communication Time(v) · Absolute Position Offset(v) · Velocity FIR(dd) · [Serial Encoder Frame] HW(dd?) SW(dd) · Res: counts/rev(ro)
- **EnDat 2.1** (f40/44): Direction(dd) · Clock Frequency (MHz)(dd) · Input Glitch (ns)(dd) · Serial Data Polling(dd) · Error Bit Mask(dd) · Communication Time(v) · Absolute Position Offset(v) · Velocity FIR(dd) · [Serial Encoder Frame] HW=19(v) SW=16(dd) Rotary Multi-turn=16(v) High Bits Mask(dd 0..8) · Res: counts/rev(ro)
- **EnDat 2.2** (f48) ★이 드라이브: Direction(dd) · Clock Frequency (MHz)=5.000(dd) · Input Glitch (ns)=120(dd) · Serial Data Polling=Every TS(dd) · **Error Bitwise Mask=0x0(v, dd 아님)** · **Read EnDat External Temperature=No(dd)** · Communication Time=60(v) · Absolute Position Offset=0(v) · Encoder Maintenance(btn) · Velocity FIR=Disabled(dd) · [Serial Encoder Frame] HW=19 SW=16(dd) Multi-turn=16 High Bits Mask=0(dd) · Res: counts/rev(65536 추정, 잘림)
- **Hiperface** (f51): Direction(dd?) · HW Sensor Resolution (Bits)(v) · High Bits Mask(dd) · Rotary Multi-turn Res(v) · Multiplication Factor(dd) · Hiperface serial status polling(dd Inactive) · Glitch Filter (Cycles/sec)(v) · Absolute Position Offset(v) · Velocity FIR(dd) · Res: cycles/rev(ro) counts/rev(ro). (Serial Encoder Frame 그룹 없음)
- **IAI** (f55/58): Direction(dd) · Clock Frequency(dd,ro) · Input Glitch(dd) · HW Res Bits(dd) · SW Res Bits(dd) · High Bits Mask(dd) · Rotary Multi-turn Res(dd) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time(v) · Absolute Position Offset(v) · Encoder Maintenance(btn) · Velocity FIR(dd) (인라인형)
- **Kawasaki** (f61): Direction(dd) · HW Res(ro?) · SW Res · High Bits Mask(dd) · Rotary Multi-turn(dd) · Clock Frequency(ro) · Input Glitch(dd) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time=79(v) · Absolute Position Offset(v) · Velocity FIR(dd) · Res: counts/rev(ro)
- **Mitsubishi** (f66): Direction(dd) · Clock Frequency=5.000(ro) · Input Glitch=120(dd) · HW=26(dd) · SW=23(dd) · High Bits Mask(dd) · Rotary Multi-turn=16(dd) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time=70(v) · Absolute Position Offset(v) · Encoder Maintenance(btn) · Velocity FIR(dd)
- **Panasonic** (f75): Direction(dd) · HW=17(dd) · SW=14(dd) · High Bits Mask(dd) · Rotary Multi-turn(dd 0/16) · Clock Frequency(ro) · Input Glitch(dd) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time(v) · Absolute Position Offset(v) · Encoder Maintenance(btn)
- **Sanyo / Nikon** (f78): Panasonic와 동일 뼈대 (HW17/SW14/Multi-turn16, Clock 2.500, Glitch 240)
- **SSI** (f84/88/91): Direction(dd) · Clock Frequency(dd) · Input Glitch(dd) · **Sensor Data Presentation=Binary(dd)** · **First Clock Delay (us)=0.0(dd)** · Serial Data Polling(dd) · Error Bit Mask(dd) · Communication Time(v) · Absolute Position Offset(v) · Velocity FIR(dd Disabled/2..8) · [Serial Encoder Frame] HW=19(dd?) SW=16(dd) Rotary Multi-turn=16(v) High Bits Mask(dd 0..8) Position LSB(v) Error Bit Number(dd) Protocol Total Bits(v) · Res: counts/rev(ro)
- **Tamagawa** (f94/97): Direction(dd) · HW=17(dd) · SW=14(dd) · High Bits Mask(dd) · Rotary Multi-turn=16(dd) · Clock Frequency(ro) · Input Glitch=240(dd) · Serial Data Polling(dd) · Error Bitwise Mask(v) · Communication Time=60(v) · Absolute Position Offset(v) · Encoder Maintenance(btn) · Velocity FIR(dd) · Res: counts/rev=16384(ro)
- **Serial Exclusive #3** (f101): Direction(dd) · HW=19(v) · SW=16(dd) · High Bits Mask(dd) · Rotary Multi-turn=16(v) · Clock Frequency(dd) · Input Glitch=120(dd) · Protocol Total Bits=19(v) · Position LSB=0(v) · Sensor Data Presentation=Binary(dd) · First Clock Delay(dd 0.0..6.0/0.4) · Error Bit Mask(dd) · Serial Data Polling(dd) · Communication Time(v) · Absolute Position Offset(v) (인라인형)
- **Gurley** (f105): Direction(dd) · HW Sensor Resolution (Bits)(dd 10/11/12) · Multiplication Factor(dd) · Quad Glitch Filter (Cycles/sec)(v) · Input Glitch Filter (nanosecond)(v/dd) · Absolute Position Offset(v) · Velocity FIR(dd) · Res: cycles/rev(ro) counts/rev(ro)

## 부속: "Serial Encoder Frame" 팝업 (f90)
HW Sensor Resolution(edit) / SW Sensor Resolution(dd) / Rotary Multi-turn Resolution(edit) / High Bits Mask(dd 0..8) /
Position LSB Number / Error Bit Number / Protocol Total Bits + 비트프레임 다이어그램 + OK/Cancel.

## 드롭다운 옵션 사전 (확인분)
- Use Digital Halls: No, Yes · Direction: Non Invert, Invert · Signal Type: Current, Velocity, Position
- Resolver Frequency [kHz]: 10, 5, 2.5, 1.2 · Input Glitch Filter (ns): 40,80,120,160,200,240,280,320,360
- Clock Frequency (MHz): 1.250, 2.500, 5.000 · Error Bit Mask: False, True · High Bits Mask: 0..8
- Velocity FIR Filter Window: Disabled, 2..8 · Rotary Multi-turn (Panasonic): 0, 16
- First Clock Delay (us): 0.0..6.0 step 0.4 (16개) · HW Sensor Resolution (Gurley): 10, 11, 12

## 미확정
드롭다운 목록 최상단 4~5행의 리스트 내 정확 표기(패널 표시로 이름만 확정) / EnDat2.2·Mitsubishi·Panasonic·Sanyo·IAI·SerialExcl#3의 Resolution 값(잘림) / Kawasaki HW·SW 비트값 / 일부 열린 드롭다운에 가린 값들.

## 명령 매핑 (별건 — feedback_spec 인코딩 시 CR/cmdmap 매핑으로 라벨→CA[] 브리지 필요)
확정분: Direction=CA[54] · Glitch Filter=CA[35] · Clock=CA[36] · HW Res Bits=CA[59] · Multi-turn=CA[62] · counts/rev=CA[18]/파생 · Error(Bitwise) Mask=CA[8] · Use Digital Halls=CA[20] · Absolute Position Offset=CA[91]대(소켓). 나머지(Serial Data Polling, Communication Time, Velocity FIR, SW Res, High Bits Mask, First Clock Delay, BiSS Mode 등)는 라벨→CA[] 추가 매핑 필요.
