# Failure Ledger — 실패·막다른길 원장 (append-only)
새 항목은 파일 끝에 추가. 항목 삭제 금지. 틀린 내용은 해당 항목에
`정정 YYYY-MM-DD:` 줄을 덧붙여 바로잡는다.

## 2026-07-12 — Elmo 2013 CR의 센서-ID enum이 2020 펌웨어엔 불완전 — 실드라이브가 오라클
- 시도: fable-reader가 CR(Ver1.406, 2013)에서 EnDat=ID 9로 매핑
- 실패 이유: 실드라이브(FW 2020) CA[41]=30 반환. CR enum이 신규 펌웨어의 센서타입(EnDat 2.2=30, 멀티턴 16bit)을 커버 못함. commut(5)/res(19)/counts(65536)는 CR과 일치했으나 센서 ID만 문서보다 확장됨
- 대안·다음엔: 센서 타입 목록은 CR enum이 아니라 드라이브 personality(.NET CreatePersonalityModel)에서 받아야 완전. 임시로 라이브값(30)을 지도에 반영, 미지 ID는 'ID N (미확정)' 폴백
- 재사용 자산: elmo_link.py ElmoLink.read_feedback/SENSOR_IDS — C:/Users/user/Fable5-Elmo-Control-Program/elmo_link.py
