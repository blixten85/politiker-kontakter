# Kommuner utan stöd

Av Sveriges 290 kommuner saknar nedanstående 37 stöd i scrapern (`scraper/scraper.py`).
För varje kommun har det undersökts specifikt vilken offentlig källa till
kommunfullmäktiges kontaktuppgifter som finns – men ingen av dem uppfyller
kravet på en fullständig, namngiven ledamotslista med faktiska (inte gissade)
e-postadresser. De återstående 253 posterna i `REGIONER` (kommuner + regioner)
har verifierats fungera. Gotlands kommun (som även är region) täcks redan av
`REGIONER`-posten "Region Gotland", vars Troman-register
(`gotland.tromanpublik.se`) vid verifiering gav 109 riktiga e-postadresser av
110 profiler.

Anledningarna grupperas nedan efter typ av brist.

## Bara presidiet har publicerad e-post

Kommunen publicerar en fullständig namngiven ledamotslista, men endast
ordförande/vice ordförande har faktiska mailto-länkar – inget mönster anges
för resten av ledamöterna.

- **Ovanåkers kommun** – endast ordförande + kommunsekreterare har e-post, ingen fullständig ledamotslista hittad.
- **Säffle kommun** – endast 3 av ca 50 namngivna ledamöter (presidiet) har e-post.
- **Vilhelmina kommun** – endast 3 av 28 ordinarie ledamöter (ordförande, 1:e/2:e vice ordförande) har e-post.
- **Skurups kommun** – endast 3 av 41 ledamöter (Ingvar Wennersten, Björn Hortevall, Kent Johansson) har e-post; övriga 38 saknar mailto och profillänk.
- **Årjängs kommun** – endast 3 av 35 ledamöter (Robin Olsson, Bengt-Olof Lorentzon, Katarina Johannesson) har `@pol.arjang.se`-adresser; inget mönster anges för resten.

## Bara gruppledare (en per parti) har publicerad e-post

- **Arvidsjaurs kommun** – "Kontakta politiker"-sidan listar bara 5 av 23 ledamöter (partigruppsordförande), med ett oifyllt textmönster "fornamn.efternamn" som platshållare snarare än riktiga adresser.
- **Älvsbyns kommun** – fullständig 31-personslista finns, men bara de 7 gruppledarna (en per parti) har e-post, med ett explicit angivet mönster `förnamn.efternamn@politik.alvsbyn.se` som uttryckligen gäller endast gruppledare.

## Presidium + gruppledare, inte hela rådet

- **Vännäs kommun** – ca 9 namngivna personer (ordförande, vice ordförande, kommunalråd, en gruppledare per parti) har e-post av 31 ledamöter; sidan anger explicit att detta bara gäller gruppledare.
- **Vårgårda kommun** – endast kommunalråd/oppositionsråd (4 personer) av 41 ledamöter har e-post; fullständig lista nås bara via en extern sökfunktion ("Hitta politiker").
- **Smedjebackens kommun** – endast kommunalråd (`fredrik.ronning@smedjebacken.se`) och oppositionsråd/gruppledare har publicerad e-post, men på inkonsekventa domäner (smedjebacken.se, moderaterna.se, mp.se, sd.se, en gmail.com) – inget enhetligt kommunmönster för de 35 ledamöterna + 22 ersättarna.

## Fullständig namnlista men helt utan e-post

Kommunen listar samtliga ledamöter med namn och parti, men ingen enda
e-postadress (bara en generisk `kommun@...`-adress) finns publicerad någonstans.

- **Falköpings kommun** – 51 namngivna ledamöter, ingen e-post.
- **Färgelanda kommun** – fullständig lista, bara generisk `kommun@fargelanda.se`.
- **Grums kommun** – fullständig lista, länkar bara till externa partisajter.
- **Habo kommun** – 35 namngivna ledamöter, ingen e-post.
- **Markaryds kommun** – 35 namngivna ledamöter med foto/parti, ingen e-post.
- **Pajala kommun** – ren textlista med namn/parti, ingen mailto, inget externt register.
- **Skinnskattebergs kommun** – ca 25 ordinarie + 17 ersättare namngivna, bara generisk `kommun@skinnskatteberg.se`.
- **Uppvidinge kommun** – fullständig lista, ingen e-post.

## Externt inloggnings- eller söksystem (Ciceron, W3D3, Unikom, diariet.\*, eget ASP-register)

Den fullständiga ledamotslistan finns bara bakom ett sök- eller
inloggningsbaserat verktyg utan garanterat, kommunövergripande e-postmönster.

- **Bodens kommun** – "Politikerportalen" hänvisar till Ciceron Assistent, som kräver inloggning (BankID eller användarnamn/lösenord).
- **Bollnäs kommun** – externt sökregister `ediariet.bollnas.se` (dessutom nedstängt vid verifiering).
- **Enköpings kommun** – W3D3 Ledamotspublicering (`w3d3extern.enkoping.se`).
- **Håbo kommun** – endast en icke-fungerande JS-sökwidget, ingen statisk lista.
- **Hörby kommun** – externt "Unikom"-register (`sok-hby.unikom.se`).
- **Höörs kommun** – externt "Unikom"-register (`sok-hr.unikom.se`).
- **Kiruna kommun** – `diariet.kiruna.se`, ett eget inloggnings-/sökbaserat system.
- **Ljusdals kommun** – Ciceron-diarium (`diariet.ljusdal.se`); kommunens egen sida har bara mailto för presidiet.
- **Luleå kommun** – JS-driven SPA ("Sök politiker") som villkorligt visar kontaktuppgifter efter sökning, ingen statisk lista att skrapa.
- **Mellerud kommun** – endast nedladdningsbara PDF-listor plus ett inloggningskrävande e-tjänstsystem (`etjanst.mellerud.se`); bara generisk `kommunen@mellerud.se`.
- **Nordanstigs kommun** – huvudsidan har mailto bara för presidiet; fullständig lista nås via ett JS-SPA-baserat diarium (`diariet.nordanstig.se`).
- **Ronneby kommun** – hänvisar bara till Ciceron-sökverktyget (`ciceronsok.ronneby.se`), ingen statisk mailto-lista.
- **Sandvikens kommun** – W3D3RepresentativePublishing (sessionsbaserat ASP.NET-register); testad profilsida gav bara generisk `medborgarservice@sandviken.se`.
- **Sjöbo kommun** – eget legacy ASP-sökformulär ("WinessInternetFms", `fmsweb.sjobo.se`), kräver sökning per person/parti/nämnd, ingen statisk lista.
- **Söderköpings kommun** – externt e-diarium-sökverktyg.
- **Strömstads kommun** – W3D3RepresentativePublishing (`searchport.stromstad.se`).
- **Vansbro kommun** – fullständig ledamotslista bara via externa Ciceron Sök; den enda statiska kontaktsidan är gruppledare-only (6 personer).
- **Östra Göinge kommun** – fullständig lista bara via externt "Unikom"-sökregister (`sok-og.unikom.se`); kommunens egen sida innehåller ingen lista eller e-post alls.

## Webbplats otillgänglig vid verifiering

- **Högsby kommun** – domänen gav konsekvent HTTP 503 vid verifiering (möjlig WAF/geo-blockering); sökresultat pekar mot en dedikerad kommunfullmäktige-sida, men inga mailto-länkar kunde bekräftas direkt.

---

*Detta dokument beskriver läget vid senaste verifiering. Om någon av dessa
kommuner uppdaterar sin webbplats med en fullständig, namngiven ledamotslista
och faktiska (inte gissade) e-postadresser kan den läggas till i `REGIONER`
i `scraper/scraper.py`.*
