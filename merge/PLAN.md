# Tekken5-Tekken3-Merge: Dr. B, Ogre, True Ogre, Gon, Gun Jack in Tekken 5

Kopie von `Tekken5Decomp` (seit 20.10.2026 auf aktuellem Stand c10dc5303, siehe CLAUDE.md „Basis“). Das Original bleibt Vanilla.
Diese Kopie ist bewusst ein Mod: die 1:1-Paritätsregel gilt hier nur für alles außerhalb der
neuen Charaktere.

## Prioritäten (Stand 20.10., Reihenfolge = Abarbeitung)

Ziel (Nutzer): alle fünf 1:1 wie in T3 (Modell, Moveset, Posen, Portrait, Gimmicks …) und
fehlerfrei in T5. Jede Stufe erst im Spiel prüfen (headless + Bild), dann notieren + committen.

- [x] **P0 Stand im neuen Build prüfen (20.10.):** alle fünf im Kampf, Grafik ok, Ogre gegen
      Paul fehlerfrei. Dabei gefunden + behoben: nur 62 freie TOC-Einträge für 94 Mod-Dateien –
      44 Kostüm-Unterdateien (Slots 82–88) wurden nie geladen. TOC + Wortsummen jetzt in
      `merge.rs` nach 0x122000 / 0x126000 kopiert und auf 0x700 Einträge erweitert (11 Patches
      in den Zugriffsfunktionen 0x23F378/0x23F5C0/0x23FAA8/0x23FCB0, `merge/patches.csv`).
- [x] **P1 Gimmick Gon (20.10.):** klein wie in T3. T3: 3DMK-Kopf Wort 1 = Größe in %
      (FUN_80035bc0 → Spieler +0x4EC/+0x4EE), FUN_80038970 skaliert damit die Wurzelposition;
      Modell-Offsets sind schon klein (Gon-Beine 198 statt Pauls 458). Vorher setzten alle
      Animationen (T3 unskaliert, Vorlage, gemeinsame T5-Bank) das Becken auf volle Höhe →
      Gon riesig mit gestreckten Beinen. Jetzt `t3_moveset_to_t5.scale_to_body`: Float-Kanäle
      Knochen 0/1 (Wurzel, Becken) exakt skaliert (`t5_anim.scale_floats`: Faktor + Grundpose):
      T3-Animationen × Größe/100, Vorlage × Beinlänge Figur/Vorlage, gemeinsame Bank (TK5DATA1
      Datei 18, 832 Animationen, Ids 0x8000+k) skaliert in die eigene Bank kopiert. Ausgenommen:
      Wurf-Opfer-Moves `*_y` (laufen auf dem Gegner) und 0x8000 `motOrigin` (umgebogen hing das
      Laden des Kampfs). Für alle fünf angewendet (Ogre ×1,04, True Ogre ×0,99, Gun Jack ×0,875
      gegen Jack-5, Dr. B ×0,86/0,9). Im Fenster geprüft, auch getroffen/am Boden. Treffer-
      kugeln folgen dem Skelett → hohe Angriffe gehen über Gon (Spieltest Nutzer offen).
- [ ] **P2 Gimmick Dr. B (nur Dr. B):** kann nicht lange stehen (Rücken) – T3-Stand-Kette
      (Stand → Umfallen/Liegen nach Zeit) und Bodenspiel aus dem T3-Moveset übernehmen.
- [ ] **P3 Füße verbuggt** (Nutzer 13.10.) – Ursache finden (Skinning/Retargeting/geteilte Ressource).
- [ ] **P4 True Ogre Schlangenhand + Schwanz bewegt** (Sekundärbewegung FUN_80037cbc als Animation).
- [ ] **P5 Moveset 1:1 Rest:** übrige T3-Requirements/bedingte Ketten, Intros, Reaktionen ohne
      Paar, gemeinsames T3-Animationspaket (TOC 279, Gon-Stand zerriss den Körper).
- [ ] **P6 Stimmen:** T3-VAB `0x60+4m` → T5-Voiceclips.
- [ ] **P7 Rest-UI:** Namensanzeige im Kampf, übrige 0x21-Grenzen (Ranglisten, Speicherstand, Endings).
- [ ] **P8 Charakterbilder Ogre / True Ogre (Nutzer 20.10., niedrige Priorität):** große
      Auswahlbilder zu klein – Gesicht auf Höhe und Größe von Devil Jins Bild verschieben und
      skalieren (Devil Jin = Vorlage). Außerdem stehen die P2-Bilder auf der falschen Seite
      (links statt rechts). Werkzeug `tools/t5_portraits.py`, Quellen `merge/png/t3_to_t5_portraits`.

### Testablauf (20.10.)

Headless lässt sich das Intro-Video im neuen Build nicht überspringen (Fensterbuild schon,
Ursache offen). Daher Tests im Fenster: `t5-bevy` mit `T5_SHOTS=<ordner>` (ein Bild pro
Spielsekunde), `T5_WARP=1` (= F3), `T5_HOLD=0.15`, eigene Kopie von `memcard`,
`T5_FORCE_SLOT=0:<slot>` und `--press START@20 … START@62` alle 1,5 s (überspringt Intro,
landet im Story-Modus, Auswahl wird erzwungen, Story-Text übersprungen) → Kampf ab ~70 s.

## Ausgangslage

- Weder Tekken5Decomp noch Tekken3Decomp kannten die Charakterdatenformate; beide übersetzen
  nur Code, die Daten kommen unverändert von der Disc.
- Quellen der fünf Charaktere:
  | Charakter | PS1 Tekken 3 (Tekken3Decomp) | Arcade History Tekken 3 (T5-Disc, Programm `tekken3`) |
  |---|---|---|
  | Ogre, True Ogre, Gun Jack | ja | ja (PS2-Port der Arcade-Fassung) |
  | Dr. B, Gon | ja (nur PS1) | nein |

## Tekken-5-Daten (Arbeitspaket 1)

- TK5DATA0 = 44 Videos (FUN_002400c8 → IPU-Wiedergabe), unwichtig. Spieldaten = TK5DATA1.
- Inhaltsverzeichnisse im Hauptprogramm: TK5DATA1 @0x0046B730 (0x623 Einträge (Sektor, Größe),
  1355 belegt), TK5DATA0 @0x0046E848. `tools/t5_archives.py` → `merge/tk5data{0,1}_toc.csv`.
- `tools/t5_unpack.py` → `merge/extracted/tk5data1/<idx>.bin` (entschlüsselt: XOR, Schlüssel
  k0 = Index, k' = 5k+3, Neustart je 2048-Byte-Sektor, FUN_0023f510; Wortsumme gegen 0x0046E9B8,
  alle 1355 korrekt; 30–71 = NPSF-Musik, unverschlüsselt) und `tk5data1_lz/` (253 ganz
  LZ-komprimierte Dateien, FUN_001f1250 = `tk5data.lz_decompress`).
- Laden: FUN_0023fba0(Index, Ziel, Max) über Warteschlange (FUN_0023faa8). Index aus
  FUN_001f09b8(id, Typ), Typtabelle 0x00462F98 {s16 Basis, u16 Art}: Art 2 → `Basis + id*11 +
  230`, Art 1 → `Basis + id*4 + 1110`, Art 0/6 → `Basis + id`. Maximalgrößen je Typ 0x0046AF38
  (3 Spalten, Spielmodus wählt). Handler je Typ 0x00467440 (12 Byte: Funktion, Flags).
- Containerformat überall: `u32 n`, n × (u32 Offset, u32 Größe).
- Charakter-/Kostüm-Slots (Art 2): 80 IDs × 11 Dateien (Index 230..1109); benachbarte IDs mit
  gleichen Dateien 0–9 = Kostüme eines Charakters.
  | Sub | Typ | Inhalt |
  |---|---|---|
  | 0, 2, 4 | 3, 5, 7 (Handler 0x0022A370) | LZ, „COM“ = Moveset (MovesetInfo, s. TKMovesets) |
  | 1, 3, 5 | 4, 6, 8 | Container 6 Blöcke = Animationen (Block 0 Format 0x64) |
  | 6, 7 | 9, 10 | meist leer |
  | 8, 9 | 11, 12 | 30–440 KB / 80–250 KB (noch offen) |
  | 10 | 88–106 (Handler 0x0022AE40) | Container 19 Blöcke = Kostümmodell |
- Kostümmodell (z. B. Datei 240): TIM2-Texturen (171 Bilder), Meshes „NUDP“ (594 KB, 40 KB),
  „MIF“, „TK5 SPLJNT“, „MOP\x03“ und weitere Tabellen.
- Spielerstruktur (FUN_00224ce0): `+0x12` Spieler, `+0x3e` Kostüm-/Modell-Slot, `+0x40`
  Charakter (0x12 → Mokujin-Sonderfall), `+0x42` Moveset-Slot. Moveset-Typ 3/4 (normal), 5/6
  (Flag 0x80), 7/8 (Flag 0x100). Mokujin: Moveset-Slot aus Tabelle 0x00466770 (30 Einträge,
  erster Slot je Moveset-Charakter). Spielerzeiger 0x003A88D0[Spieler]; LZ-Puffer je Spieler
  0x7C9EC0 + Spieler*0x1F640.
- Ladebildschirm-Portraits: Typ 42, Index `187 + n`, 43 TIM2 (456x448, 8 Bit); Reihenfolge
  Paul, Paul-R, Law, Lei, King, King-R, Yoshimitsu, Nina, Hwoarang, Xiaoyu, Christie, Jin,
  Julia, Kuma, Panda, Bryan, Bryan-R, Heihachi, Heihachi-R, Kazuya, Kazuya-R, Lee, Steve, Marduk,
  Mokujin, Eddy, Eddy-R, Jack-5, Roger Jr., Anna, Wang, Wang-R, Ganryu, Asuka, Bruce, Baek,
  Baek-R, Devil Jin, Devil Jin-R, Raven, Raven-R, Feng, Jinpachi. `tools/tim2png.py`,
  Übersichten in `merge/png/`.

## Tekken-5-Modellformat (Arbeitspaket 1, Stand 13.10.)

- Kostümmodell = Unterdatei 10 (Typ 88..106, Handler FUN_0022ae40 → FUN_002203b0 legt ein
  Objekt mit Vtable 0x152D30 an, Modelldaten in Feld 6). Container 19 Blöcke, Meshes = „NUDP“
  (bei Datei 240: Block 2 = 594 KB, Block 5 = 40 KB).
- NUDP: „NUDP“, u32 Größe, u32 Zähler (03 51 42 00), 0, dann Datensätze à 0x40 (nicht
  lückenlos; Kennung: Wort an +0x18 = 0x1040000x): +0 Bytes (Flags/Material, z. B. 20 00 00 25),
  +4 u16 1, +6 u16 Vertexanzahl, +8 Hüllkugel (x, y, z, r), +0x18 Tag, +0x28 Datenoffset,
  +0x2C Größe in QW, +0x34 Knochenpalette (u16 0, dann Bytes, 0xFF = leer; Werte 0x8x =
  Markierung?). Datenpaket = VIF-Strom: NOP (imm = Größe), STCYCL 1/5, UNPACK V1-32 @0
  (Vertexanzahl), V3-32 @1 Positionen (Gleitkomma, Bindepose, y oben, Höhe ≈ 2120), V3-32 @2
  Normalen, V2-32 @4 UV (0..1), STCYCL 1/2, V4-32 @0xCC Gewichte (4), V4-8 @0xCD Knochen-Slots
  (×7 = Matrix-Quadwords), STCYCL, maskiertes V1-32 (6 Steuerwörter, Bedeutung offen:
  Strip-/Primitiv-Info), MSCAL 0. `tools/t5_model.py` (Parser), Punktwolke
  `merge/png/t5_points.png` zeigt Paul in T-Pose (Beine noch unvollständig erfasst).
- **Topologie (gelöst):** ein Dreiecks-Strip pro Paket, Wechselrichtung nach Vertexindex, kein
  Dreieck endet an einem ADC-markierten Vertex. Die ADC-Markierungen sind VIF-Befehle: UNPACK
  V1-32 maskiert bei STCYCL CL=0/WL=5 liest keine Daten und schreibt nur den Maskenwert in
  Position.w; `0x7006 80YY` = 6 Schreibvorgänge ab 0xYY = Vertex k, k+1 (k = (YY−1)/5),
  `0x700B…` = 11 = k..k+2. Danach STCYCL 1/1 + STMASK. `tools/t5_model.py`:
  `vif_batches` (CL/WL korrekt, Fill-Modus) + `strip_triangles`. Datei 240: 374 Pakete,
  7161 Dreiecke, 99,6 % passen zu den Vertexnormalen; `merge/png/t5_mesh.png` = Paul in T-Pose
  vollständig (zusätzliche Hand-Varianten neben der Hüfte).
- **NUDP vollständig (13.10.):** Kopf `NUDP`, u32 Größe, Bytes (3, 0x51, Gruppenzahl, 0), 0.
  Gruppen ab 0x20 (`t5_model.groups`): u8 Flags (0x20/0x24), 0, 0, u8 Hauptknoten, u16 Batches,
  u16 Vertexsumme, f32 Hüllkugel[4]; je Batch 0x28 Byte: 4 Render-Wörter (Wort 0 =
  0x1040_0000 | **Material**; Wörter 1–3 = Render-Zustand, z. B. 0x23A0/0x2130/0x80000042 für
  undurchsichtig), u32 Datenoffset, u16 Quadwords, u16 VIF-Pakete, u32 0, u16 0, u8 Palette[10]
  (Knotenindizes, 0xFF frei). Datei 240: 66 Gruppen, 172 Batches.
  **Material** = Index unter den großen TIM2-Bildern (die 96 Bilder 8×2 = Farbpaletten-Varianten
  zählen nicht mit); bestätigt: Paul texturiert korrekt (`merge/png/t5_costume.png`).
  **Block 5** = zweites Mesh = nackter Grundkörper (22-Knoten-Skelett in Block 6, Material 479
  aus anderer Datei, vermutlich Unterdatei 8/9) – für eigene Modelle unsichtbar machen.
  **VIF-Paket** (≤ 40 Vertices): NOP (num 0x91, imm = Paketgröße), STCYCL CL5/WL1, V1-32 @0
  (Anzahl), STMASK 0x80 (w aus COL), V3-32 maskiert @1 Positionen, V3-32 @2 Normalen,
  V2-32 @4 UV, STCYCL CL2/WL1, V4-32 @0xCC Gewichte, V4-8 usn @0xCD Palettenplatz×7,
  STCYCL CL0/WL5, STMASK 0xFFFFFF7F (w aus ROW = ADC), ADC-Befehle (erster bei Vertex 0),
  NOP-Füllung, STCYCL 1/1, STMASK 0, MSCAL 0 (Paketende auf 16 Byte). Alle Adressen mit FLG.
- **Skelett (Block 3 des Kostümcontainers, bei Datei 240):** Kopf u16 0x32, u16 Knotenanzahl
  (141), f32 1,04, Offsets: Eltern (s32 je Knoten, −1 = Wurzel), lokale Verschiebung (3 f32),
  lokale Drehung (3 f32 Euler, Bogenmaß), Liste animierter Knoten (u32 n = 30, Indizes 1..30).
  Hierarchie: 0 Wurzel (y 1196), 1 Becken, 2–3 Wirbelsäule, 5 Hals, 6 Kopf, 7–10 / 11–14 Arme,
  4 Unterkörper, 15–17(+21) / 18–20(+22) Beine, 23–54 Hilfsknochen, 55–84 Finger, 85–110
  Gesicht, 111–136 Stoff, 137–140 Extras. Block 6 = Skelett des 2. Meshes (22 Knoten).
  Knochenwerte in den Mesh-Paletten (bis 0x8C) = Knotenindizes. Zuordnung T3 → T5: T3-Teile
  auf Körperknoten 1–22; True Ogres Schlange/Schwanz auf freie Hilfs-/Stoffknoten.
- **Moveset-Tabelle (COM):** in der PS2-Fassung bei 0x180 (nach 2 × 36 Alias-u32 + 36 u16),
  23 × (Offset, Anzahl); die Reihenfolge weicht von TKMovesets `Structs_t5.h` ab (dort als
  „move“ geführter Eintrag 11 sind Cancel-ähnliche Daten) → Tabellenzuordnung klären.
  Animationsblock (Unterdatei 1, Block 0) beginnt `64 00 79 01 17 00 0b 00 …` = T5-Muster aus
  TKMovesets plus Halbwort 0x0179.
- Offen: Datensatz-Varianten (lange Paletten 0x55..0x69, Gruppen), Bedeutung Palette/0x8x,
  Steuerwort-Typen 6/B, Skelett („TK5 SPLJNT“, „MIF“-Blöcke), Texturbindung (TIM2
  Block 1), Animationsformat (TKMovesets: 0x64).

## Erster spielbarer Test (13.10.): Ogre als Pauls Kostüm

- `tools/t3_to_t5.py`: T3-Mesh auf T5-Bindepose (Skelett aus Block 3, Euler zyx = Rz·Ry·Rx;
  Slot→Knoten SLOT_NODE: Brust 1→3, Hüfte 11→4, Kopf 2→6, Arme 3–6→7–10 / 7–10→11–14, Beine
  12–14→15–17 / 15–17→18–20; Sekundärteile vorerst starr am Knoten des Elternteils). Vertices
  bleiben teil-lokal, Nahtgewichte 0,5/0,5. Vorschau `merge/png/t3_on_t5_22.png` (passt ohne
  Achskorrektur).
- `tools/t5_costume.py`: schreibt eine Kostümdatei aus einer Vorlage: TIM2 = Vorlagenbilder bis
  zum letzten 8×2-Streifen + eigene 8-Bit-Texturen (je T3-UV-Eintrag zugeschnitten, CLUT CSM1,
  Farbe 0 = Alpha 0), NUDP (eine Gruppe je Batch, ≤ 13 Dreiecke, ≤ 10 Knoten, Render-Zustand
  0x23A0/0x2130/0x80000042), MIF passend zur Gruppenzahl, Grundkörper (Block 5) auf Nullpunkt
  zusammengefaltet, übrige Blöcke unverändert. Grenze Typ 88: 1 683 776 Byte.
- Gegenprobe: `t5_render.py` liest die erzeugte Datei und zeigt Ogre korrekt
  (`merge/png/t5_ogre_roundtrip.png`). Originalmodelle haben bis 197 Gruppen (wir 102).
- Eingespielt über `merge/data/files.csv`: 240 → `ogre/costume_0240.bin` (Paul Kostüm 1),
  251 → `ogre/costume_0251.bin` (Paul Kostüm 2).
- **Test 1 (Nutzer, 13.10.): Schwarzbild nach dem Stage-Laden.** Log: „VU1: program at 0x0 did
  not end“ (975×, im Original nie; „unknown call target 0x002ee6e0“ ist Rauschen, auch im
  Original). Gegenprobe: eigener Encoder erzeugt für ein Original-Batch byte-gleiche Pakete
  (bis auf ADC). Verdacht: Grundkörper (Block 5) auf einen Punkt gefaltet → 484 degenerierte
  Dreiecke → VU1-Schleife hängt. Geändert: Grundkörper auf 2 % um (0, 1150, 0) verkleinert
  (keine degenerierten Dreiecke mehr) – half nicht allein.
- **Selbsttest headless (Nutzer erlaubt 13.10.):** Eingaben `--press START@42 START@48 DOWN@53
  CROSS@55 RIGHT@60..64 CROSS@66` → Survival, Paul (Kampf ab ~90 s). Bisektion: nur Grundkörper
  verkleinert = ok, neues Mesh = Hänger. Diagnose `T5_VUHANG=<dir>` (vu.rs: Startzustand +
  letzte 256 Block-PCs des ersten hängenden VU1-Laufs). Ursache 1: Render-Wörter 1/2 sind
  **Offsets in den Zustandsbereich des NUDP-Blocks** (zwischen Gruppentabelle und Daten, Blöcke
  à 0x30: Licht, VU1-Funktionstabelle für Befehl 0xEC → VU-Adresse 49); fehlte → Funktionszeiger
  0 → Endlosschleife 0→6→C. Fix: Bereich der Vorlage übernehmen, Offsets umrechnen.
  Ursache 2 (Ogre einfarbig): Wort 0 = 0x1040_0000 | **Textur-ID (GIDX)** aus dem TIM2-Bildkopf
  (Erweiterung „eXt“ + „GIDX“ bei Kopf+0x48, u16), nicht die Bildposition. IDs sind pro Datei
  reservierte Bereiche (Kostüm 1: 0–543, Kostüm 2: 768–1319) → eigene Texturen bekommen freie
  IDs entfernter Kostümtexturen. **Ergebnis: Ogre texturiert im Kampf, keine Hänger**
  (Headless-Bilder: Ogre gegen Lee/Asuka).
- Violette „Fläche“ = **Ogres Haar** (Nutzer 13.10.), Sekundärkette Datensätze 21/22 am Kopf.
  Fehler war: Sekundärteile ohne Offset zum Elternteil und ohne Ruhedrehung. Jetzt
  (`t3_to_t5.record_frames`): Offset (w9, w10, −w11) entlang der Kette, Kettenanfang an einer
  Hand = Armrichtung (True Ogres Schlange), sonst nach hinten unten (0, −0,7, −0,7) (Haar,
  Schwänze von True Ogre und Gon). Headless: Ogre mit wehendem Haar gegen Law, keine Hänger.
- **Eigene Proportionen (Nutzerwunsch 13.10.):** `t3_to_t5.fit_skeleton` setzt im Skelettblock
  (Block 3) der Kostümdatei die Knoten-Verschiebungen so, dass jeder zugeordnete Knoten auf dem
  T3-Gelenk liegt (T3-Offset im Eltern-Knotenraum, Zwischenknoten wie Wirbelsäule/Hals
  anteilig skaliert); Struktur (141 Knoten) bleibt → Animationen greifen weiter. Headless: Ogre
  steht mit eigenen Proportionen in Kampfhaltung (gegen Asuka).
- Bekannte Mängel:
  Sekundärteile starr, Moves/Animationen von Paul.

## Tekken-5-Animationen (Stand 13.10.)

- **Bank** (Moveset-Unterdatei 1/3/5, Block 0): u8 0x64, u8 0, u16 Anzahl (Paul 377), u16 23,
  u16 Deskriptor[23] = (11,11,5,7,7,7,11,7,7,7,7,6,7,7,7,6,7,7,6,7,7,6,7), u32 Offset[Anzahl]
  (ab Bankanfang, 0 = leer), dann Rohanimationen ohne Kopf (TKMovesets setzt denselben Präfix
  davor).
- **Codec** (`tools/t5_anim.py`, Decoder nach TKMovesets ParseAnimation0x64, eigener Encoder):
  u16 Frames (dekodierbar 1 … Frames−1), u8 Short-Shift, u8 Float-Shift, u16 Float-Knochen,
  f32 Faktoren, Grundpose, u32-Tabelle je 16 Frames, je Kanal Kopfbyte (Größe<<2 | 2 Bits) +
  MSB-first-Codes (4-Bit-Präfix: ±4/±20/±84/±340/±1364/±5460, 13 = 16 Bit, 14 = Wiederholung,
  15 = Ende); erster Code = Keyframe relativ zur Grundpose, dann zweite Differenzen.
  Rundtest: alle 377 Paul-Animationen dekodieren → kodieren → dekodieren ohne Abweichung.
- **Bedeutung** (FUN_002c7008 → Quaternion; Decoder FUN_002c6680, Wurzel/Hüfte FUN_0025a310):
  Deskriptor 4–7 = Achse aus Kugelwinkeln (a, b) + Drehwinkel θ: Achse = (cos b·cos a,
  cos b·sin a, sin b), q = (Achse·sin θ/2, cos θ/2); 6 = Gelenke mit nur θ (Ellbogen, Knie).
  Float-Knochen 0, 1, 6 = Positionen (1 = Hüfte, z. B. (0, 1428, 0)).
  Test (`tools/t5_posetest.py`, `merge/png/v_grid.png`): nur „lokal = Bind · Anim“ mit dieser
  Achse ergibt eine aufrechte Kampfpose. Zuordnung Anim-Knochen → Knoten (Hypothese MAP_A:
  2→1, 3→2, 4→3, 5→4, 7→5, 8→6, 9–12→7–10, 13–16→11–14, 17–19→15–17, 20–22→18–20) – nicht
  bestätigt: Bildraster über 6 Animationen (`merge/png/g_grid.png`) teils plausibel, teils
  gekippt. **Belegt (13.10.):** MAP_A stimmt – Scharnier-Deskriptor 6 sitzt genau bei Anim 11/15/18/21
  = Unterarm/Schienbein (Knoten 9/13/16/19 laut Elternkette), Messung im Spiel
  (`tools/t5_anim_probe.py`: Knochen k in allen Animationen um 90° gedreht, Ogre-Slot) zeigt
  Anim 8 = Kopf, 18 = Bein, 11 = Arm. FUN_002c7008: Komponente 0 = Winkel a, 1 = b (Achse),
  2 = θ; q = (Achse·sin θ/2, sqrt(1 − sin²θ/2)). Früherer Text: Zuordnung belegen – entweder im Code (Verbraucher der
  Quaternionen aus FUN_002c7008, Aufrufer 0x0025B548/0x002C7xxx) oder im Spiel messen
  (Headless-Diagnose: Animationsnummer/Frame + VU1-Palettenmatrizen aus Befehl 0x1CC loggen
  und gegen die eigene Rechnung abgleichen).

## Kader-Erweiterung (Entscheidung Nutzer 13.10.: echte Erweiterung, IDs 33–37)

Die Kostüm-Lösung (Ogre als Paul) ist nur Testgerüst. Ziel: fünf zusätzliche Charaktere mit
eigenen Auswahlfeldern, Namen, Portraits, Movesets, Animationen; alle 33 Originale bleiben.

Befunde:
- Grenze 0x21 in 35 Funktionen (0x20/0x21 zusammen 115), u. a. Auswahl (FUN_0028f448,
  FUN_0028fd68, FUN_00290078), UI-Sprite-Tabellen je Charakter (Namen `PAU_wl` 0x479C48,
  Ranglisten-Gesichter `ranking_arc_face_pau` 0x3BB728, Gesichtsicons `kao_MAR` 0x3BC920),
  Speicherstand/Records (FUN_0012c840), weitere UI (0x0029xxxx).
- Spielerstruktur (0x3A88D0[Spieler]): +0x40 Charakter, +0x3E Modell-Slot, +0x42 Moveset-Slot
  (gesetzt in FUN_00215948 aus DAT_00155198[Spieler]); Tabellen je Charakter z. B.
  Lebenspunkte PTR_DAT_004631c8[+0x40] (FUN_001f0ab8).
- Statische Suche nach Tabellenzugriffen ist wegen der dekompilierten Ausdrucksformen
  unzuverlässig.

- **Slot-Tabelle `DAT_00465b68`** (80 × 0x24, Index = Slot = Spieler +0x42, 0x50 = Grenze):
  u16 Charakter-ID (+0x40), u16 Kostüm, u32 Feld 2 (Index für FUN_00239230/48/60 = Namen-
  /Zeiger-Tabellen, z. B. PTR_PTR_0046a2e8), u32 Feld 4, u32 Feld 6, u32 Feld 8, u32 Feld 10,
  u32 Feld 12 (Suchschlüssel), u16 Feld 14 (Flag), u32 Feld 16 = Funktionszeiger
  (0x218AC0/0x218AB8/0x2D1828/0x2D18A8). Gekapselt in Zugriffsfunktionen 0x218BB8–0x219150
  (direkte Getter: FUN_00218bb8 ruft Feld 16, 218c20/218ec8 Feld 0, 218e90 Feld 1,
  218d18/218d60/218da8/219020 Feld 2, 218c58 Feld 4 (Mokujin-Sonderfall +0x40==0x12),
  218ca8 Feld 6, 218ce0 Feld 8, 218fa8 Feld 10, 219150 Feld 14; Suchen über alle 80:
  218fe0 (ID→Feld 2), 219060 (ID→Feld 12), 2190a0 (Feld 12→ID), 219110 (Feld 2→Feld 12)).
  **Plan:** diese Funktionen per Hook (`sheets/hle.csv` → `merge.rs`) für Slots ≥ 80 aus einer
  Erweiterungstabelle (`merge/data/slots.csv`) bedienen, Suchen inklusive Erweiterung; neue Slots
  80–84 laden ihre 11 Dateien über `res:<typ>:<slot>`. Danach Tabellen je Charakter-ID
  (+0x40: Lebenspunkte PTR_DAT_004631c8, Namen 0x47A6E8, Auswahl, …) gleich behandeln.

Vorgehen:
- **A Kern (Kampf):** Charakter-ID 33 im RAM erzwingen (Auswahl-Ergebnis patchen) und im
  Headless-Lauf jede fehlschlagende Tabelle finden: Diagnose, die Lesezugriffe hinter das Ende
  bekannter 33er-Tabellen meldet bzw. Lesen über Index ≥ 33 protokolliert. Jede Tabelle wird
  verlängert (verlegt + Zeiger/Immediates gepatcht über Sheets bzw. HLE) – Mechanik der
  Mod-Schicht: `ram.csv` + Hooks.
- **B Auswahl:** Layout Datei 81 (ASBF/ASPT) entschlüsseln, neue Knoten (Icons, Namen, Bilder)
  und Raster-Felder; Struktur `+0x58 + i*4` (33 Zeiger) verlegen.
- **C Modi/Speicher:** Arcade/Story/Endings, Records.
- Animationen: Zuordnung Anim-Knochen → Knoten belegen (T5_VUSNAP-Diagnose), Encoder steht.

### Umsetzung Kader-Erweiterung (13.10.)

- **Slots 80–84** (`merge/data/slots.csv`): Ogre 33, True Ogre 34, Gun Jack 35, Gon 36, Dr. B 37
  (Charakter-ID = Namensindex Feld 2). Hooks auf alle Zugriffsfunktionen der Slot-Tabelle,
  Charakter-Datensatz (FUN_00218ac8, Tabelle 0x3ABF88 nur 32 Einträge → eigene Datensätze),
  Freischaltung (FUN_00218c10, 32-Bit-Maske), Namenstabellen FUN_00239230/48/60 (Kürzel für
  `kao_<kurz>`, GROSS, voll). Modelle über `res:88:<slot>`. Headless: Ogre, True Ogre, Gun Jack im
  Kampf (Slot-Test per `T5_FORCE_SLOT=<spieler>:<slot>`), keine Hänger.
- **Freier RAM für Tabellen:** MIPS-Code im RAM wird nie ausgeführt (statisch übersetzt) →
  0x00120000.. (`MOD_AREA` in merge.rs): Icon-Array, Raster, Charakter-Datensätze, Namen.
- **Code-Patches** `merge/patches.csv` + `tools/merge_patch.py` (Instruktions-Sheet, Bytes + p-code),
  danach `gen_rust.py`. Auswahl-Arbeitsstruktur (Pool-Objekt 0x180 Bytes, voll belegt) hat das
  Icon-Array bei +0x58 (33 Einträge, dahinter Felder) → nach 0x120000 verlegt, Schleifen 0x26.
- **Raster** (FUN_0024ba50, Zeiger je Modus 0x4719E8 → 31 Zellen {u16 char, s8 hoch, s8 runter,
  u8 links, u8 rechts}); neu `merge/data/grid.csv` (tools/t5_grid.py), 36 Zellen.
- **Layout Datei 81** (tools/t5_layout.py, Zeigerkarte tools/layout81_pointers.txt aus RAM-Vergleich
  Datei ↔ geladenes Layout): ASBF-Knoten 0xF0 = Objekt im Speicher (FUN_002aeb60 relokiert nur),
  je Knoten ein Clip 0x8C + Befehlsblock, Wurzel-Clip mit RObj-Instanzliste (Position doppelt:
  Knoten +0x90 und RObj +0xC). ASPT: 3 Tabellen à count (Name, TIM2, ungenutzt).
  Neue Icons = Klon von kao_PAU. Reihen y −50/−103/−156/−209, Spalten x = −241 + 48·c.
- **Portraits** (tools/t5_portraits.py, Quelle Nutzer-Renders `merge/png/t3_to_t5_portraits`,
  Ogre-/True-Ogre-Icons aus kao_ogre.png/kao_true_ogre.png): Icon 56×56 im Rahmen von kao_PAU
  (Innenfläche x 10–46, y 7–48), Portrait 456×448 L/R (T5: 187.., Typ 42) mit Transparenz;
  weißer Hintergrund per Randfüllung + Entmattierung entfernt.
- T3-Versus-Portraits: BNS 14..35 = ein LZ-Strom (TIM 8 Bit 126×252), 12/13 Container aus LZ-
  Stücken (tools/t3_portraits.py).
- Offen: Namensschriftzüge (name_X_L/R, Tabelle 0x47A6E8 + DAT_00177270 je 33), Portrait-IDs
  (Typ 42), eigene Movesets/Animationen, weitere 0x21-Grenzen (Ranglisten, Speicherstand).

### Grafikfehler Gon / Gun Jack / Dr. B (13.10., behoben)

- **Texturgrößen:** der GS kennt nur Zweierpotenzen (TEX0 TW/TH aus der Bildgröße); Gon, Gun
  Jack, Dr. B hatten große ungerade T3-Ausschnitte (160×184, 240×208 …) → UVs gestreckt.
  `t5_costume.textures` rundet jetzt auf Zweierpotenzen.
- **Tabellen pro Slot/Charakter hinter dem Tabellenende:** `DAT_00482028` (3 Floats je Slot, 80
  Einträge, FUN_003049d0 per Slot, FUN_00304d40 per „Slot − Kostüm“) – Slot 88 las ~1e21 →
  riesige Dreiecke, Slot 80 NaN, Slot 85 ≈ 0. Verlegt nach 0x121400 (120 Einträge, Vorlagenwerte;
  merge/patches.csv). Neue Slots fortlaufend je Charakter (Ogre 80/81, True Ogre 82/83, Gun Jack
  84/85 Vorlage Jack-5 47/48, Gon 86, Dr. B 87/88) wie im Original.
- **Charakter-ID im Kampf = Vorlage** (merge.rs `fight_char`, FUN_00218c20 setzt +0x40): viele
  33er-Tabellen per +0x40 (Trefferkugeln 0x3AB478/0x3AB560, 0x3B2FD0, Speicherstand-Statistik
  FUN_002c9f78). Neue IDs 33–37 nur in Auswahl/Namen/Portraits.
- Diagnose-Weg: Bisektion der Dreiecke im Spiel (`tmp bis.sh`), Slotnummern-Tausch, RAM-Vergleich
  Slot 88 ↔ 89, Assembler-Suche nach `lh …,0x42(…)` mit Tabellenindex.

### T5-Animationen: Konvention im Spiel gemessen (13.10.)

- Wahrheit aus dem RAM: lokale Knotenmatrizen des Spielers bei 0x9D7810 (P1, 141 × 4×4,
  Zeilenvektor-Form, Translation = Skelettblock); laufender Frame per Scharniergelenken bestimmt
  (`tmp/py/truth.py`: Paul Animation 271, Frame 58).
- Kanal (a, b, θ): FUN_002c7008 baut Rx(a), dreht jede Zeile mit Ry(b), Achse = 3. Zeile
  k = (sin b·cos a, −sin a, cos b·cos a); lokale Drehung = Rotation um k mit **−θ** und **ersetzt**
  die Bind-Drehung (Bind liefert nur die Translation). Ellbogen/Knie (Format 6) = Rz(−θ).
- Zuordnung (gemessen): Knochen 4 → Knoten 2 (Wirbelsäule), 5 → 4 (Unterkörper), 7 → 5,
  8 → 6, 9–12 → 7–10, 13–16 → 11–14, 17–19 → 15–17, 20–22 → 18–20. Knochen 2/3 erreichen das
  Becken nicht (Knoten 1 = Einheit), Knoten 3 (Brust) hat keinen Kanal. Knochen 1 = Becken-
  position (y oben, Stehen ≈ 1040–1120), Knochen 0 = Vorwärtsbewegung, Knochen 6 ≈ (−400, 0, 0).
- T3 → T5 (`tools/t3_anim_to_t5.py`): Zielweltdrehung = A · R(T3-Teil), A = diag(1, −1, −1);
  Wirbelsäule übernimmt die T3-Brust. Bank-Neubau `tools/t5_bank.py`, Vorschau `tools/t5_pose.py`.
  Im Spiel geprüft: Ogre in T3-Standhaltung (alle Animationen = T3-Zug 0), aufrecht, korrekt.

### Movesets: Stand der Formate (13.10.)

**T5 „COM“ (Slot-Unterdatei 0, LZ):** Kopf 0x26C Byte (MovesetInfo 0x180 + Tabelle 23 × (Zeiger,
Anzahl) + Motionsliste); **alle Zeiger relativ zum Ende des Kopfes: Dateioffset = Zeiger + 0x26C**
(belegt: im RAM reloziert, Paul bei 0x155A980). Listen in TKMovesets-Reihenfolge (Structs_t5.h):
reactions 80 B, requirement 4, hitCondition 12, pushback 12, pushbackExtra 2, cancel 24,
groupCancel 24, cancelExtra 4, extraMoveProp 8, (begin/end 0), move 76, voiceclip 2, inputSeq 8,
input 4, A1 2, mvlPlayable 20, mvlInput 4, mvlDisplay 44, A3 8.
- Move (76 B): +0 Name, +4 Animationsname (z. B. „Co_zenStL0“ / „Mco_FLT1(DVD)“), +8 Animations-ID
  (0x4000 + k = eigene Bank Unterdatei 1, Paul 377; 0x8000 + k = gemeinsame Bank), +0xC vuln,
  +0x10 hitlevel, +0x14 Cancel-Index, …
- Cancel (24 B): u32 Befehl (oberes Halbwort Tasten, unteres Richtung; 0x8000 = Listenende,
  0x8001–0x80xx Sonderbefehle, 0x8005 = Gruppenverweis), Requirement, Ziel-Move, Extradata,
  u16 Erkennung von/bis, Startframe, Option. Paul: Stand-Move 226 „Pl_sKAM00_“.
**T3-Charakterpaket:** Kopf u16 +2 Move-Anzahl, u32[] Offsets: +4 Cancel-Liste (12 B: Befehl,
Ziel << 16, Optionen), +8 Moves (56 B: Animation, vuln, hitlevel, Cancel-Index, Übergang, …),
+0x1C Animationen. Vorläufer des T5-Formats (gleiche vuln-Werte 0x842/0x1052 …). **T3 entschlüsselt (Tekken3Decomp):** Paketkopf +2 Move-Anzahl, +4 Cancels, +8 Moves (56 B),
+0xC Move-Zeigertabelle (4023 × u32: < 0x40000000 = eigener Move, sonst gemeinsames Paket
DAT_800adc28), +0x10 (Liste ×2), +0x14 (Liste ×4, über FUN_8002d2c8), +0x18 Bitmaske der
Tabelle, +0x1C Animationen, +0x28. Loader FUN_8002ce14: Move-Wort 0 = Animation, 3 = Cancel-Index
(×12), 7 = ×2-Liste, 8 = ×4-Liste, 10 = Übergang (Tabelle 0x80017C10, sonst −4 + Paket+0x28).
Cancel (12 B, FUN_8002de24): u16 Befehl, u8 Bedingung (Spielerzustand), u8 Requirement (< 0x45,
FUN_8002e0bc), u16 –, u16 Ziel (Index in die Move-Zeigertabelle, FUN_8002d178), u8 Option
(Bits 0–5 Übergang, 6/7 Flags), u8 Frame von, u8 Frame bis, u8 Startframe. Befehl
(FUN_8002cc28): 0xC000 Listenende, 0xC00C Gruppe (gemeinsame Liste 0x80017C78 + s[3]·12),
< 0xC000: Bits 0–3 Tasten, Bit 4 Flag, Bits 5–13 Richtungen; 0xC001/0xC002 Sonderprüfungen,
0xC00E–0xC04C / 0xC7FF– Eingabefolgen (Tabellen 0x800954D0 / 0x800955CC).
Noch offen (siehe unten): gemeinsames Paket (Datei), Bedeutung der Bedingungen/Requirements, Treffer-
und Schadensdaten (Listen +0x10/+0x14), Umsetzung nach T5.
Offen (alt):
T3-Befehlskodierung (Richtung/Tasten, z. B. 0x409, 0xC00C) und Ziele > Move-Anzahl (gemeinsame
Moves / Flags) – aus dem T3-Code (Tekken3Decomp) zu entschlüsseln; dann Umsetzung der
Requirement-/Property-IDs T3 → T5 (keine Tabelle vorhanden).

**Weitere Befunde (13.10.):**
- Gemeinsames T3-Paket = Spiel-ID 0x49 → **TOC 279** (332 Moves; `bns_read` bildet Spiel-IDs über
  die Tabelle 0x80098574 auf TOC-Einträge ab – unsere Werkzeuge nutzen TOC-Nummern direkt).
- T3-Move (56 B), aus dem Code: +0x00 Animation, +0x04 vuln, +0x08 ?, +0x0C Cancel-Liste,
  +0x10 u16 Folge-Move nach Animationsende (Index in die Zeigertabelle), +0x12 s16 Drehung,
  +0x14 (FUN_8002d2c8), +0x18 u8 Animationslänge, +0x19/+0x1A u8, +0x1C ×2-Liste, +0x20 ×4-Liste,
  +0x24 Flags (0x70000000 …), +0x28 Übergang, +0x2C u8 Schaden (→ Gegner +0xEE), +0x2D/+0x2E u8
  aktive Frames, +0x34 u16 Index in die Angriffseigenschaften 0x800177DC.
- T5-Befehl (TKMovesets ConvertCommand): Richtung = unteres Halbwort (T7-Bits 0x2 d/b, 0x4 d,
  0x8 d/f, 0x10 b, 0x20 n, 0x40 f, 0x80 u/b, 0x100 u, 0x200 u/f), Tasten = Bits 16–23
  (1 LP, 2 RP, 4 LK, 8 RK), Bits 24–31 Flags; 0x8005/0x8006 Gruppe, ab 0x8013 Eingabefolgen.
  T3-Richtungsbits liegen 4 Bit höher (0x20 … 0x2000) → T5-Richtung = T3 >> 4 (zu bestätigen).
- T5-Move: +0x18 u16 Übergang, +0x1C u16 (Folge?), +0x20 Hit-Condition-Index, +0x2C Voiceclip,
  +0x30/+0x34/+0x38 Extraprops (−1 = keine), +0x40 Hitbox, +0x44/+0x46 aktive Frames (Paul
  Jab 10–11). Animationslänge noch nicht gefunden.
- Plan Konverter: T5-Moveset aus der Vorlage (Paul / Jack-5) aufbauen, Systemmoves (Gehen,
  Treffer, Aufstehen) behalten, jeden T3-Angriff als geklonten Vorlage-Angriff mit T3-Animation,
  -Schaden, -Frames, -Höhe und umgerechneten Cancels anlegen.

### Moveset-Port Stufe 1 (13.10., im Spiel geprüft)

`tools/t3_moveset_to_t5.py <m> <Modell> <Ausgabe> [Vorlagen-Slot]` (Werkzeuge: `t3_moves.py`
T3-Leser, `t5_com.py` COM-Parser/Schreiber bytegenau, `lzpack.py` Namco-LZ-Packer,
`t5_bank.py`, `t3_anim_to_t5.py`): Vorlage Paul (Gun Jack: Jack-5, Slot 47). Jeder Vorlagen-
Cancel (Liste + Gruppen) mit gleichem Befehl wie ein T3-Standbefehl (T3-Move 0) und Angriffsziel
→ Klon des Vorlagen-Angriffs mit T3-Animation, -Schaden (Trefferbedingung neu), -Aktivframes.
Stand (Alias 1) und Richtungsbefehle ohne Taste (Gehen) mit T3-Animation. Würfe (Schaden-Flag
0x4000) noch Vorlage. Ergebnis: `merge/data/<char>/moveset.bin` + `bank.bin`, `res:3:<slot>` /
`res:4:<slot>`. Headless: Ogre in T3-Haltung, T3-Schläge treffen; Gon, Dr. B, Gun Jack laufen.
Offen (Stufe 2): Folgeketten/Strings der T3-Moves (eigene Cancel-Listen statt der Vorlage),
Eingabefolgen (T3 0xC00E…), Hocke/Sprung-Angriffe aus anderen Zuständen, Würfe samt
Gegneranimation, Trefferhöhen/Reaktionen, Vorlagen-Befehle ohne T3-Entsprechung entfernen.

### Moveset-Port Stufe 2 (13.10., im Spiel geprüft per Move-Log)

Werkzeug-Diagnose: `t5-headless` mit `T5_MOVELOG=<sek>` protokolliert den aktuellen Move beider
Spieler (Spielerstruktur `0x3A88D0[p] + 0xC0` = Zeiger auf den Move-Eintrag, Kopien bei +0xC4,
+0x7D4; gemessen per RAM-Abzügen) mit dem Logikzähler 0x151F90. Auswertung im Job-Tmp
`py/movelog.py` (Basis der Move-Liste per Signatur im RAM-Abzug; die COM-Zeiger sind im RAM
umgerechnet, Felder ohne Zeiger wie vuln/hitlevel/Frames bleiben gleich). Der Konverter schreibt
`merge/data/<char>/clones.txt` (neuer Move → T3-Move, Vorlage).

Befunde (alle im Konverter `tools/t3_moveset_to_t5.py` umgesetzt):
- **Richtungen:** T5-Richtungsbits = T3 >> 4, **0x20 = neutral, 0 = beliebig** (nicht T3-n → 0!).
  T5-„beliebig“-Einträge ohne T3-Gegenstück → T3-Neutralangriff.
- **Strings:** T5-Cancel `0x20 << 24 | Tasten << 16 | Richtung`, extradata 9, Fenster/Start =
  T3-Cancel (frame from/to, start = Aktivframe). Jeder Klon bekommt eine eigene Cancel-Liste aus
  seiner T3-Liste + tastenlose Vorlageneinträge + Ende `0x8000` bei T3-Länge. Bestätigt: Ogre 1,1
  (T3 100 → 153 nach Frame 10), Jab dauert 40 Logikframes = T3-Länge.
- **Trefferhöhe/vuln:** T3-Move-Wort 1 = T5 vuln (identisch, 0x842). Wort 2 = hitlevel; Byte 1
  (Stufe) T3 → T5: 1→1 (tief), 2→2 (mittel), 3→4 (Spezial-mittel), 4→5 (hoch), 6→7
  (unblockbar), Rest gleich (bestätigt an 15 Charakteren in beiden Spielen).
- **Trefferbedingungen** sind Listen (Konter zuerst, …), Ende = Eintrag, dessen Requirement-Liste
  mit **0x141 (T5-Requirement-Ende)** beginnt. Gruppen-Cancel-Listen enden mit 0x8006; Aufruf
  0x8005 mit Move-Feld = Gruppenstart, Startframe-Feld = Länge.
- **Reaktionen:** T3-Move **+0x32** (u16) = Reaktions-ID. `tools/t3_reactions.py` lernt T3-ID →
  T5-Reaktion aus den 15 gemeinsamen Charakteren (Paul −6/0, Law −4/2, Lei −2/5, King 0/7,
  Yoshimitsu 2/9, Nina 4/12, Hwoarang 6/14, Xiaoyu 8/16, Eddy 10/21, Jin 12/25, Julia 14/28,
  Kuma 16/30, Bryan 18/32, Heihachi 20/34, Anna 30/51 = T3 m / T5-Slot), T5-Reaktionen über
  den Inhalt (Namen der Reaktions-Moves) verglichen. Deckung 60–85 %, Rest = Vorlage.
  Reaktionseintrag (80 B): 7 × u32 Pushback, 6 × u16 Richtungen, …, ab +52 14 × u16 Moves.
- **Würfe:** T5 und T3 gleich gebaut. Versuch → Cancels mit Seiten-Requirement (**gleiche IDs:
  2 vorne, 3 hinten, 4/5 Seiten, Parameter 1536**) → Ausführung `*_n` (Werfer), deren
  Trefferreaktion den Gegner in `*_y` (Opfer, im Moveset des Werfers) schickt. T3: Ausführung N
  (vuln 0x842), Opfer N+1 (vuln 0x3884). Port: Ausführung + Opfer geklont, Opfer-Animation auf
  Pauls Skelett (beliebiger Gegner). Bild geprüft: Ogre hebt Jin, Jin landet passend.
- **Wurzelbewegung:** T5-Knochen 0 = horizontale Verschiebung seit Frame 0 (Paul f+3: z 28 →
  813), Knochen 1 = Becken. `t3_anim_to_t5.convert` legt jetzt die T3-Wurzelbewegung in Knochen 0
  (vorher alles im Becken → Figur sprang am Ende zurück).
- Allgemeine Kontext-Moves der Vorlage (`Co_…` außer Sprung, `Thr…`) werden nicht ersetzt.
- **T3-Bedingung 107 = immer:** alle 90 Stand-Einträge mit Bedingung 107 der 15 gemeinsamen
  Charaktere haben ein T5-Gegenstück ohne Requirement (1+2, 3+4, d/f+1+2 …). Ogre 1+2 (T3 168,
  unblockbar) im Spiel bestätigt (193 Logikframes = T3-Länge).
- **Gemeinsames T3-Paket – NICHT verwenden:** Animationswert ≥ 0x40000000 → TOC 279 dekodiert
  zwar plausibel (`t3_anim_to_t5.anim_source`), aber Gons Stand (Move 0) von dort ergab im Spiel
  einen zerrissenen Körper mit riesigem Keil (Headless 13.10., schon bei „ROUND 1“). Entweder
  passt die Animation nicht zu Gons Skelett, oder Gons Werte zeigen auf ein anderes Paket.
  `convert` liefert dafür None (Vorlage bleibt); nur die Beckenhöhe (Siegerposen-Kriterium) nutzt
  die Quelle. Klären, bevor gemeinsame Animationen übernommen werden.
- **Zustandspaare:** von (T5-Stand, T3-Move 0) aus über gleiche tastenlose Befehle (Richtungen;
  Dash T5 0x8001/0x8002 = T3 0xC001/0xC002) → eigene Cancel-Liste je T5-Zustand (Gruppen
  eingebettet), Angriffe aus dem T3-Zustand, Animation des Zustands aus T3. Nur Namen aus
  `PAIRABLE` (Gehen, Dash/Lauf, Rückdash, Sprünge, Stand↔Hocke, Hockgehen): dieselbe Richtung ist
  in T5 ein Seitschritt, in T3 ein Sprung; Drehungen, Aufstehen u. Ä. bleiben T5.
  Ausgaben `merge/data/<char>/states.txt`.
- **Siegerposen:** T5-Moves `*_Win_A…E`, `*_Win_Round` (Ende der Liste, davor `*_Start_A/B` =
  Intros, Aliase 0–35 = System-Moves). T3: unter den letzten 40 eigenen Moves die von Stand aus
  unerreichbaren, ≥ 90 Frames, vuln 0x842, aufrecht endend, ohne Sprung (Becken ≤ 130 %).
  Ogre 322/323/324/328 (Vorschau: Arme hoch/Brüllen), Gun Jack 381/383/387, Gon 362/363,
  Dr. B 634. Intros bleiben Vorlage (T3 ohne eindeutige Entsprechung).
- Abdeckung erreichbarer T3-Angriffe (BFS ab Move 0): Ogre 54+/137, Gun Jack 96/189, Gon 55/119,
  Dr. B 54/190 (vor Bedingung 107). Rest v. a. bedingte Ketten (T3-Requirements 36–38, 48, 61
  …: Seitenwechsel, Rücken, Konter) – Requirement-IDs T3 ↔ T5 sind nur für Würfe (2–5) belegt.
- Offen: T3-Requirements ↔ T5 allgemein, Intros, Reaktionen ohne Paar (15–40 %).

### Fehler „nur gegen Paul (P2)“ (Nutzer 13.10.) – drei geteilte Ressourcen

Reproduktion: `T5_FORCE_SLOT=1:0` (P2 = Paul Slot 0) + neuer Charakter als P1 → P1 verzerrt
(Pauls Körperform/Texturen, gestreckte Keile, Füße). Gegen Paul Kostüm 2 (Slot 1) fehlerfrei,
also nur gegen den **Vorlage-Slot** (Gun Jack entsprechend gegen Jack-5 Slot 47).
1. **Moveset-Cache/Spiegelkampf** (`FUN_00224ce0`): Schlüssel der zwei Moveset-Puffer
   (`DAT_00156154`, bleibt über Kämpfe erhalten!) = Spieler +0x3E | Flags. **+0x3E ist der
   Moveset-Charakter** (Slot-Tabelle Feld 8: Paul 0, Jack-5 18 – nicht der Modell-Slot), bei uns
   = Vorlage → P2 teilt P1s Moveset/Bank (bzw. Cache-Treffer auf Pauls Daten aus einem früheren
   Kampf). +0x3E global zu ändern geht nicht (~60 Tabellenzugriffe). **Fix:** `merge/patches.csv`
   6 × `lh …,0x3e` → `0x42` (Slot) an 0x224ED0, 0x224FA4, 0x224FB4, 0x224FBC, 0x22502C, 0x225030;
   gleicher Slot teilt weiter. Gebaut (headless + bevy). Geprüft: Typ 3/4 jetzt für id 0 und 86
   geladen; Paul gegen Paul unverändert ok.
2. **Kostüm-Unterdateien 2–9** (Typ = Basis + 3; Typtabelle 0x462F98: Typ 3..12 → Basis 0..9,
   Typ 88 → 10) fielen für unsere Slots auf die Dateien des Vorlage-Slots zurück (gleicher
   Index → Ressourcen-Cache teilt sie). **Fix:** `merge/data/files.csv` eigene Einträge
   `res:<b+3>:<slot>` → `../extracted/tk5data1/<230+11·Vorlage+b>.bin` (6/7 gibt es bei Paul
   nicht). Danach Gun Jack gegen Jack-5 fehlerfrei, Gon gegen Paul: Körper richtig, Kopf-
   texturen noch falsch →
3. **Textur-IDs (GIDX)**: `build_tim2` nahm IDs entfernter Vorlagenkostüm-Texturen → gleiche IDs
   wie ein echter Paul Kostüm 1. IDs liegen in 768er-Blöcken je Kostümdatei; frei (von keiner
   der 80 Originaldateien genutzt): 18, 19, 38, 39, 62, 63, 67–73, 75, 79. **Fix:**
   `tools/t5_retex.py <model> <block>` nummeriert unsere Bilder (nach dem letzten 8×2-Streifen)
   und die Render-Wörter 0x1040_0000|ID um; angewendet: Slots 80–88 → Blöcke 18, 19, 38, 39, 62,
   63, 67, 68, 69 (Sicherungen `*.pre_retex`). **Nach jedem Neubau eines Modells mit
   t5_costume.py erneut ausführen.** NOCH NICHT IM SPIEL GEPRÜFT (Testläufe hingen im Intro-Video,
   Tastenzeitpunkte bei Last verpasst – einzeln laufen lassen).

## Tekken 5: Charakterauswahl

- Auswahl-Bildschirm: FUN_0028f218 (Zustandsmaschine; wartet auf Typ 0x26, lädt Typ 0x2C).
  Layout = Datei 81 (Typ 36): Container aus „ASBF“ (Namco-Layout, Knoten `name_PAUL_L`,
  `DrawMid`, `ReOS…`) + „ASPT“ (Sprites/Texturen). Weitere ASBF-Dateien: 74, 186.
- Namenstabelle 0x0047A6E8: 33 × {u32 ID, Zeiger `|name_X_L`, `_R`}: 0 Paul, 1 Law, 2 Lei,
  3 King, 4 Yoshimitsu, 5 Nina, 6 Hwoarang, 7 Xiaoyu, 8 Christie, 9 Jin, 10 Julia, 11 Kuma,
  12 Panda, 13 Bryan, 14 Heihachi, 15 Kazuya, 16 Lee, 17 Steve, 18 Marduk, 19 Mokujin, 20 Eddy,
  21 Jack-5, 22 Roger, 23 Anna, 24 Wang, 25 Ganryu, 26 Asuka, 27 Bruce, 28 Baek, 29 Devil Jin,
  30 Raven, 31 Feng, 32 Jinpachi. (FUN_00224ce0 prüft `+0x40 == 0x12` für Mokujin – das ist
  eine andere Nummerierung als diese Liste; klären.)
- Fest auf 33 ausgelegt: FUN_0028f448 (Namen, Schleife < 0x21), FUN_0028fd68 (Icons, Knoten
  per sprintf(0x153DD0, …), Zeiger-Array der Auswahlstruktur `+0x58 + i*4`, ab `+0xDC` andere
  Felder), FUN_00290078 (< 0x21). Kader-Erweiterung = Strukturen verlegen + ASBF erweitern.

**Reihenfolge (12.10.):** Jeder Kostüm-Slot hat eigenes Moveset (`+0x42`) und Modell
(`+0x3e`). Konvertierte T3-Charaktere werden zuerst als Kostüm-Slot eines vorhandenen
Charakters über die Mod-Schicht getestet (ohne Code-Änderung); danach die echte
Kader-Erweiterung (Auswahlfelder, Namen, Portraits).

## Mod-Schicht (fertig, vom Nutzer bestätigt 12.10.)

`rust/crates/ps2-runtime/src/merge.rs` + `disc.rs` (virtuelle Sektoren) + `sheets/hle.csv`
(Hooks `merge_main` auf `main` 0x001F0790, `merge_file_index` auf FUN_001f09b8) + `play.bat`
(`T5_MOD=merge\data`).
- `merge/data/files.csv` (`target,file`): `target` = TOC-Index (ersetzen) oder
  `res:<typ>:<id>` (neue Ressource, z. B. neuer Slot `res:3:80`); `file` = entschlüsselte Datei
  (LZ-komprimiert, wo das Original es ist).
- `merge/data/ram.csv` (`addr,value`, hex): RAM-Wörter beim Start von `main`.
- Beim Start von `main`: Index vergeben (freie TOC-Einträge 1556–1568, 1180, 1182–1229),
  verschlüsseln, hinter dem Image-Ende ablegen, TK5DATA1 vergrößern, TOC + Prüfsumme in den RAM.
  Grenze: Seek ist s32 → ca. 170 MB Platz hinter dem Image.
- Test: `187,test/portrait_kuma.bin` → Paul zeigt Kumas Ladebildschirm-Portrait (bestätigt).

## Referenz TKMovesets (Tekken-5-Formate)

`_references/TKMovesets` (Kiloutre): `TKMovesets2/GameSpecific/Structures/Structs_t5.h`
(MovesetInfo, MovesetTable mit 23 Listen, Move, Cancel, Requirement, HitCondition, Reactions,
Pushback, Input, MotaList), `AnimExtractors/AnimExtractor_t5.cpp`, `Utils/Animations*.cpp`
(Format 0x64/0xC8, `ParseAnimation0x64`), `MovesetConverters/Converter_t5_to_t7*.cpp`. An Datei
230 bestätigt: COM = MovesetInfo (Namen-Offsets, 2 × 36 Aliases ab Wort 6/42); Zeiger in der
Datei sind Offsets.

## Tekken-3-Daten (PS1)

- `TEKKEN3.BNS` (303 Einträge, `Tekken3/extracted/bns_toc.csv`).
- Kampf (FUN_80036310): Modell `m` = Spieler `+0x1c`; BNS `0x5F+4m` „3DMK“ (Modell/Skelett),
  `0x60+4m` „pBAV“ (VAB-Kopf, Stimmen), `0x61+4m` Container (n, n × (Offset, Größe)) mit PS1-TIMs
  (Pixel und CLUTs getrennt) + Geometrie, `0x62+4m` Animationsbank (Kopf `00 00 74 01`,
  Offsettabelle, anders als T5). Vierer-Blöcke 71–94 = m −6…−1.
- Zuordnung über die Namenskachel (erstes TIM in `0x61+4m`, `merge/png/t3_names.png`):
  m −6/−5 Paul, −4/−3 Law, −2/−1 Lei, 0/1 King, 2/3 Yoshimitsu, 4/5 Nina, 6/7 Hwoarang,
  8/9 Xiaoyu, 10/11 Eddy, 12/13 Jin, 14/15 Julia, 16 Kuma, 17 Panda, 18/19 Bryan,
  20/21 Heihachi, **22/23 Ogre**, 24/25 Mokujin, **26/27 True Ogre** (Flügel-Texturen),
  **28/29 Gun Jack**, 30 Anna, 31 Tiger, 32 Xiaoyu, 33 Jin, 34 Law, 35 Anna, **36 Gon**
  (37 vermutlich Gon), **38/39 Dr. B**, 40 Anna, **45 Gun Jack**. Dateien = `0x5F+4m … 0x62+4m`.
  Tabelle 0x800958C4 (Charakter-ID → m) folgt einer anderen Nummerierung – noch klären.
- `0x61+4m`: Container mit 5 Einträgen: [0] Pixel-TIMs (4 Bit, ohne CLUT; Namenskachel,
  Movelist-Schrift, Körpertexturen), [1] Effekt-TIMs (32×32 mit CLUT), [2] TIM mit CLUTs,
  [3], [4] kleine Tabellen.
- Laden (FUN_80036310): `0x5F+4m` = 3DMK (`DAT_8009bd38`), `0x60+4m` = VAB-Kopf, Container
  `0x61+4m`: [0] Texturen → FUN_80035744 (VRAM), [1] Effekt-TIMs → FUN_8007619c, [2] mit
  VAB-Kopf → FUN_80075288 (Ton), [3] Tabelle → Spielerdaten, [4] → FUN_800784e4;
  `0x62+4m` = Animationsbank (Ziel FUN_80069e2c(Spieler +0x16)).
- **3DMK** (FUN_80035bc0, FUN_80034ee4): 27 Datensätze à 0x38 Byte ab Offset 0 (die ersten
  16 Byte von Satz 0 = Kopf: u32 27, u32 Größe in %, „3DMK“; Skalierung (w1<<12)/100:
  Ogre 105, True Ogre/Gun Jack 100, Dr. B 90, Gon 45). Satz: w4 = Vertices (SVECTOR-Liste mit
  kleinem Kopf), w5 = Liste von 41 Zeigern (selten, z. B. Hände), w6 = Normalen (×4096),
  w7/w8 = Primitive (Layout noch offen → T3-Renderer lesen), w9..w11 = Gelenk-Offset zum
  Elternteil, w12 = Elternindex (−1 = Wurzel). Offsets ohne gesetztes oberes Byte werden beim
  Laden zu Zeigern. T3-Skelett 27 Knoten vs. T5 23 (Animationskopf 0x17) → Retargeting nötig.
- Vertex-Block (w4) laut FUN_80036cac (Transformation, GTE RTPT in Dreiergruppen, Ergebnis in
  den Scratchpad 0x1F800000): zwei Listen geteilter Vertices (`u32 n`, dann n Byte-Indizes, 4 pro
  Wort; Liste 0 aus dem Scratchpad-Puffer, Liste 1 aus 0x8009BD4C – übernommene, schon
  transformierte Vertices von Nachbarteilen = Nahtschluss an Gelenken), dann `u32 N` + N
  SVECTOR. Für T5: geteilte Vertices → Gewicht auf den Knochen des Ursprungsteils.
- Vertex-Nachbearbeitung (FUN_80036cac): nach der Transformation werden Gelenk-Vertices mit
  gespeicherten Nachbar-Vertices gemittelt (Summe, dann >>1 → Gewichte 0,5/0,5) bzw. in globale
  Speicher (0x8009D550 / Scratchpad 0x1F800290) abgelegt, aus denen spätere Teile lesen.
- **Primitive (w7)**, vier Listen (`u32 Anzahl`, dann Einträge), GPU-Typ:
  1. 0x24 FT3, 2 Wörter: v0 = (w0 & 0x1FC)/4, v1 = (w0>>7 & 0x1FC)/4, v2 = (w0>>14 & 0x1FC)/4,
     Bit 24 = beidseitig, w0>>25 = Tiefen-Bias (signed); w1 & 0x1FC = Farb-/Normalenindex.
  2. 0x2C FT4, 2 Wörter: dazu v3 = w0>>23 (Byteoffset); NCLIP über v0, v1, v3.
  3. 0x34 GT3, 2 Wörter: w1 = drei Normalenindizes (& 0x1FC, >>7 & 0x1FC, >>16).
  4. 0x3C GT4, 3 Wörter: w1 Flags + Farbe 0, w2 = drei weitere Normalenindizes.
  Vertexindex = Scratchpad-Slot (4 Byte je Bildschirm-XY), max. 127 je Teil.
- **UV/Textur (w8)** (FUN_80035190 baut die GPU-Paketvorlagen): u16-Tabelle A (Wort 0 =
  Byteabstand zu B; Einträge: niedriges Byte = CLUT-Offset, hohes Byte = Texturseiten-Offset),
  u16-Tabelle B (Wort 0 = Byteabstand zur Byteliste; Einträge = UV `u | v<<8`), Byteliste:
  Anzahl FT3 + je [A, uv0, uv1, uv2], Anzahl FT4 + je [A, uv0..uv3], Anzahl GT3 + je
  [A, uv0..uv2], Anzahl GT4 + je [A, uv0..uv3] (Reihenfolge wie w7). CLUT-Basis 0x7E000000
  (y = 0x1F8, Spieler 2: 0x7F…), Texturseite Basis 0x60000 (x = 0x180, Spieler 2: 0x160000).
  Texturen (Container [0]) liegen per FUN_80035744 bei x+0x180, CLUTs bei y+0x1F8.
  → Konvertierung: virtuellen VRAM aufbauen, pro (Seite, CLUT) ein Atlas.
- `tools/t3_model.py`: Parser (Teile, Vertex-Block, Primitive, UVs); Prüfung an allen fünf
  Charakteren: Polygonanzahlen in w7 und w8 stimmen für jedes Teil (0 Abweichungen), Vertexslots
  < 128. Polygone: Ogre 316/326/73/40 (FT3/FT4/GT3/GT4), True Ogre 720/110/0/0, Gun Jack
  310/359/40/30, Gon 0/0/682/55, Dr. B 227/189/228/47.
- Vorschau nur mit Offsets (`merge/png/t3_bind_all.png`) ist verdreht/waagerecht: Gelenk-Offsets
  gelten im gedrehten Elternsystem, eine Ruhepose fehlt im Modell → Pose kommt aus der Animation
  (Euler-Winkel, FUN_8003a338 = Winkel → Matrix mit Sinustabellen 0x8001E8C4/0x8001F0C4).
- **Charakterpaket `0x62+4m`** (= Moveset + Animationen): Kopf u8 init, u8, u16 +2 Moves (Ogre
  330), 13 Abschnitts-Offsets +4..+0x34 (FUN_80069ea4 macht Zeiger daraus), +0x38/+0x3C Ende.
  Pakete je Spieler in DAT_800adc20/24, gemeinsames Paket DAT_800adc28. FUN_8002ce14: Moves in
  +8 (56 Byte: w0 Animation in Abschnitt +0x1C, ≥ 0x40000000 = gemeinsames Paket; w3 → +4
  (12-Byte-Einträge), w7 → +0x10 (×2), w8 → +0x14 (×4); Byte +0x18 = Länge in Frames;
  +0x20 = Ereignisliste (FUN_800458c8: Töne, Effekte, Handformen)). Spieler: +0x54 aktueller
  Move, +0x58 Frame, +0x4C/+0x50 voriger Move.
- **Animation** (`tools/t3_anim.py`, exakter Port von FUN_80038b4c + FUN_800387c8): u16 Kopf
  (niedrig = Frames K, hoch = Wortzahl Kanal 0), 48 Byte Wortzahlen der Kanäle 1..48, Daten ab
  Byte 50. Kanal mit n Wörtern: 0 → 0, 1 → Konstante, 2 → linear (a + b·t, >>5 bei K > 9),
  K → Wert je Frame, sonst Kurve (u16: Wertänderung (>>5) << shift, Abstand−1 in 5 Bit;
  shift 1 für Kanal 0–14, 5 für 15–48; Gewichtstabellen 0x800966F8..0x80096C20). Ungerade
  Kanäle laufen rückwärts. Ergebnis ×2 (s16). Getestet: Ogre-Standanimation plausibel.
- **Pose-Vektor** (FUN_8003ad10, Puffer DAT_800a85e8, Aufruf aus FUN_8003a87c): 0–2 Wurzel,
  3–14 vier IK-Ziele (Hände/Füße), 15–18 Beuge-Hinweise, 19–48 zehn Euler-Tripel (65536 = 360°,
  FUN_8003a338 → Matrix, Slots aus Tabelle 0x8001A330). Gliedmaßen per Zwei-Knochen-IK
  (FUN_8003b5b8, FUN_8003b9b4, FUN_8003ba28, FUN_8003bca8; Längen bei 0x80096ECC..).
- **Skelett** (Stand 13.10.): `tools/t3_pose.py` = Gleitkomma-Port von FUN_8003ad10
  (Euler-Slots [0,1,11,2,3,7,6,10,14,17], Ry90 auf 2/3/7, IK-Basen: Schultern = Slot 1 ∘ Slot 3/7
  mit (350,0,∓100), Hüfte = Slot 0 ∘ Slot 11; Ziel lokal + (−140,0,0) bzw. (−160,0,±100); IK
  FUN_8003bca8: Zielrichtung als X-Achse, Roll = Hinweiswinkel, Beugung um Z, Längen Arme
  302/232, Beine 449/446). FUN_8003afcc: Teil i = Slot i (0..17), Welt = Eltern ∘ (Slot-Rotation,
  Offset); Elternzeiger im Feld +0x40 des 0x44-Blocks (+0x8F4 Welt, +0x914 Bildschirm), Ort der
  gesetzt in FUN_80035908.
  **Gelöst (FUN_80035908):** Teil p zeichnet Datensatz 0x8001A05C[p]
  [0,1,3,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19] mit Slot 0x8001A074[p]
  [0,1,11,12,13,14,15,16,17,3,4,5,6,7,8,9,10,2]; Elternteil = w12 des Datensatzes (Teil-Index,
  −1 = Basismatrix Spieler +0x8B0); Offset = (w9, w10, −w11); Geometrie nur wenn
  0x8001A08C[p] ≥ 0. Teile 18–23 (Datensätze 21–26) = Sekundärteile (Flügel, Haare, …).
  Ketten: Hüfte (Slot 11) → Beine 12–14 / 15–17; Brust (1) → Schultern 3/7 → Arme; Brust → Kopf 2.
  Vorschau Standpose aller fünf korrekt erkennbar (`merge/png/t3_pose_22.png`,
  `t3_pose_all.png`: True Ogre, Gun Jack, Gon, Dr. B).
- **Nähte / Skinning gelöst** (`t3_model.skin`): Vertex-Block = Kopf (Byteoffset des ersten
  Misch-Slots), Liste 0 (Kopie aus Scratchpad = zuvor gezeichnetes Teil), Liste 1 (aus globalem
  Speicher 0x8009BD50), N + SVECTOR, dann Mischpässe mit fortlaufendem Slotzeiger: (a) 9-Bit
  (Index, Halbieren): s = eigen(+½) + G, G = eigen = s; (b) 2 Listen (Quelle G / Scratchpad):
  eigen = Quelle + eigen(½); (c) 2 Listen (Ziel G / Scratchpad): eigen(½) ablegen; (d) 2-Bit:
  halbieren außer Wert 1. Index k → Slot k/2 − 1. Symbolisch nachgerechnet → jeder Slot =
  gewichtete Summe (Datensatz, Vertex). Zeichenreihenfolge = PART_RECORD. Ergebnis: bei Ogre,
  Gun Jack, Gon, Dr. B haben alle gezeichneten Vertices Gewichtssumme 1 (True Ogre: 19 leere
  Verweise, vermutlich Flügel/Varianten). Vorschau mit Skinning: alle fünf geschlossen
  (`merge/png/t3_pose_all.png`). Viereck-Ecken: [v0, v1, v(>>14), v(>>23)], Dreiecke (0,1,2) +
  (1,2,3); bei Vierecken stehen Flag/Bias im 2. Wort.
- **Texturen gelöst** (`t3_model.vram`, `texel`): Container-Eintrag 0 = TIMs (4 Bit; t0/t1
  Schrift ohne CLUT, sonst je eine 16-Farben-CLUT); Pixel nach (x+0x180, y), CLUT nach
  (x, y+0x1F8). UV-Eintrag A: CLUT-Feld 0x7E00 + (A & 0xFF), Texturseite 6 + (A >> 8),
  4 Bit; Farbe 0 = transparent. Texturierte Standpose aller fünf korrekt
  (`merge/png/t3_pose_all.png`). Fehlt: Gesichter (Gun Jack, Dr. B) – Laufzeit-VRAM-Kopien
  FUN_80033d0c / FUN_80033dc8 / FUN_8003404c (Tabellen 0x800959CC, 0x8009591C, 0x800958BC,
  Rechtecke 0x8009579C / 0x8009586C) nachbilden.
- **Zweite Meshes + Sekundärteile (gelöst):** Teile mit Flag in 0x8001A044 (1, 2, 17) zeichnen
  zusätzlich Datensatz+1 auf demselben Knochen direkt danach (`t3_pose.draw_order`); Teile 18–23
  = Datensätze 21–26 (Sekundärbewegung FUN_80037cbc, in der Vorschau Ruhepose). Damit bei allen
  fünf jeder gezeichnete Vertex Gewichtssumme 1, keine leeren Verweise.
- **True Ogre (Nutzervorgabe 13.10.: die rechte Schlangenhand darf nicht fehlen):** Datensatz 21
  = Schlangenhals (Eltern Teil 12 = Hand), Datensatz 22 = Schlangenkopf (Eltern Teil 18, mit
  w5-Formliste, z. B. Maul), Datensatz 23 = Schwanz (an der Hüfte, (368, 510, 0)). Beim
  Konvertieren als eigene Knochen übernehmen und ihre Sekundärbewegung (FUN_80037cbc) in
  Animationen umsetzen. Vorschau `merge/png/t3_pose_26.png`.
- **Gesichter (gelöst, Nutzervorgabe: alle fünf):** Gesichter von Ogre, Gun Jack, Dr. B nutzen
  UV-Eintrag 0x8000 = Texturseite 0x86 = **8-Bit-Modus**, 256-Farben-CLUT bei (0, 504); die
  8-Bit-TIMs liegen im Container-Eintrag 0 (Dr. B: vier Varianten). `t3_model.texel` wertet
  den Farbmodus aus (Seite Bits 7–8), `_face_copy` bildet FUN_80033d0c nach (MoveImage,
  Tabelle 0x800959CC: True Ogre, Gon, Dr. B). Alle fünf Köpfe korrekt (`merge/png/t3_heads.png`,
  `t3_alle_fuenf.png`). Rest: violette halbtransparente Fläche an Ogres Kopf (Semi-Transparenz-
  Bits der Seite, beim Konvertieren gesondert behandeln).
- Offen T3: w5-Formlisten (Hände/Schlangenmaul,
  FUN_80034970/FUN_80034844), Sekundärbewegung, gemeinsames Animationspaket (Offsets
  ≥ 0x40000000), Moveset-Semantik.
- Charakterauswahl-Bilder: BNS `12 + Charakter` (23 Charaktere, FUN_80052520 → VRAM).
- 279–300: Animationsbanken je Charakter (Kopien).

## Arbeitspakete

1. [x] Tekken-5-Formate: Archiv, Slots, Moveset (TKMovesets), Portraits. Offen: Modell (NUDP),
   Sub 8/9.
2. [ ] Tekken-3-Formate: [x] Zuordnung m → Charakter, [x] 3DMK (Skelett, Vertices, Normalen,
   Primitive, UVs; Exporter offen), [ ] Animationen, [ ] Moveset.
3. [ ] Konverter T3 → T5: Modell + Texturen, Skelett-Retargeting, Moveset-Übersetzung.
4. [ ] Kader-Erweiterung im Code (siehe Charakterauswahl).
5. [x] Datenauslieferung: Mod-Schicht.
