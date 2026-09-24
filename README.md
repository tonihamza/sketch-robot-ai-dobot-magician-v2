# Dobot Studio — GB10 local și Windows

Pentru rulare integrală pe GB10, vezi [instalarea și utilizarea locală](GB10.md). Include interfața foto, camera cu timer, AI Qwen prin ComfyUI local, conversie SVG și control Dobot Magician prin USB.

# Dobot SVG — 80 × 80 mm, USB direct

Aplicație Python locală pentru DOBOT Magician, cu interfață în română. Nu folosește DobotLab, DobotLink, DLL-ul producătorului sau internet la rulare. Driverul USB Silicon Labs rămâne necesar în Windows.

## Pornește pe Windows

Dublu clic pe **Porneste.bat**. Mediul `.venv` și bibliotecile sunt deja instalate în proiect. Dacă altă aplicație deține COM5, deconectează robotul din acea aplicație; programul nu închide forțat alte programe. `Conectează USB` citește identificarea și poziția, fără mișcare.

## Prima calibrare

1. Fixează suportul și robotul. Montează ferm pixul. Nu schimba înălțimea pixului după calibrare.
2. Conectează USB. Indicatorul robotului trebuie să fie verde, fără alarme.
3. Privește foaia de sus, din locul operatorului. „Sus” este marginea îndepărtată. Cu butonul **Unlock de pe antebraț**, du vârful pixului până apasă pixul pe hârtie la fiecare colț cu presiunea dorită în arc; eliberează Unlock înainte de înregistrare.
4. Apasă `Memorează…` în ordinea **stânga sus → dreapta sus → dreapta jos → stânga jos**. Nu se execută mișcări automate la capturare. Contactul trebuie să fie pe foaie, nu pe partea de sus a peretelui.
5. După al patrulea punct, calibrarea validă se salvează automat în `data/calibration.json`. Dacă măsurarea este respinsă, apasă `Calibrare nouă` și repetă cele patru puncte.

Aplicația verifică o zonă dreptunghiulară XY de circa 80 × 80 mm și păstrează proporțiile desenului. Pentru pixul cu arc, **Z de contact este cel mai mare Z numeric dintre cele patru colțuri**; de exemplu, dintre −24 și −22 mm se alege −22 mm. Acest Z este constant pe tot desenul, iar corecția de teanc se adaugă separat. Diferențele de Z dintre atingeri nu mai resping calibrarea și nu înclină planul. Interfața afișează Z-ul ales. Metoda presupune foaia orizontală; nu compensează o înclinare reală a suportului. Coordonatele și unghiurile originale rămân păstrate pentru verificarea cinematică.

Aplicația nu deformează SVG-ul pentru a-l potrivi unui patrulater strâmb. La încărcarea calibrării salvate trebuie să confirmi că robotul, suportul și pixul nu s-au deplasat. Recalibrează după reset/homing, mutarea robotului/suportului, schimbarea pixului sau o lovire/pierdere de pași. Calibrările salvate anterior folosesc aceeași regulă Z maxim la încărcarea în noua versiune.

## Desenează

1. Încarcă SVG-ul. Pentru prima probă există `examples/patrat.svg`.
2. Setează marginea (implicit 5 mm), ridicarea (3 mm), corecția de teanc Z (0 mm) și viteza de desen (implicit 100 mm/s, reglabilă cu orice valoare pozitivă acceptată de controller). `Actualizează previzualizarea` reface desenul. Zona maximă este 80 × 80 mm; cu margine de 5 mm, desenul ocupă cel mult 70 × 70 mm. Limita măsurată mai mică este respectată.
3. **Cu Unlock, poziționează manual pixul în interiorul foii**, cel puțin 2 mm de margini, deasupra hârtiei, fără să scrie. Înălțimea inițială nu mai trebuie să fie apropiată de Z-ul calibrat. Eliberează butonul. Aplicația refuză să vină automat din exteriorul suportului.
4. Confirmă că există spațiu pentru **întregul braț și suportul pixului**, nu numai pentru vârf.
5. Apasă direct `DESENEAZĂ`. `Probă cu pixul ridicat` este opțională, inclusiv după schimbarea SVG-ului sau a setărilor.
6. La final pixul rămâne ridicat în interior, deasupra punctului de pornire. Mută-l manual cu Unlock pentru schimbarea foii. Nu există deplasare automată peste pereți.

### Suportul de 60 mm și hârtia la aproximativ 40 mm

Acestea sunt înălțimi față de masă, **nu coordonate robot**. Diferența de aproximativ 20 mm înseamnă că ridicarea normală de 3 mm nu trece peste perete. Toate deplasările generate, inclusiv cele dintre linii și revenirea, rămân în interiorul dreptunghiului. Aplicația nu cunoaște forma completă a suportului/brațului și nu este un detector de coliziuni; proba fizică rămâne necesară. Nu modifica limitele sau ridicarea ca să forțezi trecerea peste perete.

### Teancul de foi

Când scoți foi, suprafața coboară. Folosește o singură foaie pe un suport cu înălțime fixă pentru repetabilitate, sau reînregistrează contactele. Corecția Z în mm deplasează planul: **negativ = mai jos**, pozitiv = mai sus. Corecția Z nu mai are limita fixă ±5 mm. Se verifică accesibilitatea traseului rezultat; proba ridicată este opțională. La calibrare, comprimă arcul la presiunea dorită pentru desen, fără să-l blochezi la capătul cursei.

## Oprire și conexiune

- Un singur job robot poate rula; camera și un job AI pot pregăti simultan următorul portret. Lucrarea pornită păstrează traseele și setările inițiale. Desenarea și deplasările orizontale folosesc CP cu până la 16 puncte în avans, la pas de cel mult 2 mm. Coada se pregătește înainte de pornire și se completează în timpul mișcării. Ridicarea/coborârea verticală folosește MOVL la viteza Z reglabilă, implicit 30 mm/s. O barieră de coadă confirmă sfârșitul liniei înainte de ridicare.
- STOP întrerupe jobul și solicită `ForceStop` plus golirea cozii. Nu se ridică automat pixul după eroare/oprire, pentru a nu adăuga mișcare într-o situație necunoscută.
- La pierderea USB, oprirea prin software nu poate fi garantată; mișcările deja trimise pot continua (până la 16 puncte CP, circa 32 mm, sau întreaga mișcare verticală în curs). Nu se retransmite automat o mișcare ambiguă și nu se reia jobul după reconectare. STOP nu este oprire fizică de urgență.
- Aplicația nu face homing, nu șterge alarme automat și nu actualizează firmware. După o eroare, citește și rezolvă cauza înainte de alt job.
- Vitezele configurate rămân în controller după job. Coada de execuție este oprită și golită la început/sfârșit; nu folosi simultan programe memorate sau alte aplicații de control.

## Ce SVG-uri acceptă

Trasee, linii, polilinii, poligoane, dreptunghiuri, cercuri, elipse, curbe Bézier și arce; transformările grupurilor și viewBox sunt interpretate prin `svgelements`. Proporțiile se păstrează, desenul se centrează. Curbele sunt aproximate și simplificate la circa 0,05 mm. Traseele sub 0,05 mm sunt eliminate, ordinea și sensul sunt optimizate pentru deplasări mai scurte.

**Un SVG cu suprafețe umplute este desenat pe contur.** Aplicația nu face încă scheletizare, hașurare, vectorizare foto sau eliminarea automată a contururilor duble. Pentru desen cu pixul, exportă trasee centrale. Nu sunt acceptate text neconvertit în trasee, imagini bitmap, CSS extern, `use`, măști, clipping, filtre sau referințe externe. Importurile nesuportate sunt respinse în loc de a fi desenate incomplet. Liniile albe și fundalul alb sunt ignorate; culorile rămase se desenează cu același pix.

## Verificarea accesibilității

Pe firmware-ul 3.7.0 testat, comanda 15 (`CheckPoseLimit`) a întors ecoul cererii, nu răspunsul boolean documentat. Nu folosim acel ecou drept confirmare de accesibilitate.

Folosim geometria Magician de 135/147 mm; offseturile reperului sunt deduse din perechile XYZ/unghiuri ale celor patru colțuri și ale poziției de pornire. Inconsistența de peste 0,5 mm blochează execuția. Traiectoria completă, inclusiv ridicări, deplasări și revenire, este verificată la pas de maximum 0,5 mm. J1 folosește intervalul oficial −120…120°, fără rezerva suplimentară de 2°. Celelalte intervale conservatoare sunt J2 0…85°, J3 −5…85°, J4 −90…90°, plus distanțare față de limita combinată. Aceste limite pot refuza zone pe care robotul le-ar putea atinge: repoziționează suportul, nu extinde limitele fără verificare.

Aceasta este verificare cinematică, nu măsurare externă a preciziei și nici simulare de coliziune. Alarmele sunt citite periodic în timpul CP, iar coordonatele sunt verificate la finalul fiecărui grup de mișcări și după ridicări/coborâri. CP comandă XYZ, fără comandă explicită de orientare a pixului; verificarea cinematică include rezerva pentru variația orientării odată cu baza.

## Fișiere și instalare pe alt PC

- `start.py`, `dobot_draw/`: codul aplicației.
- `requirements.txt`: versiuni fixe.
- `tests/`: teste fără mișcări hardware.
- `data/`: calibrare și jurnale create local (nu include în distribuții calibrări pentru alt montaj).
- `wheels/`: biblioteci pentru instalare offline pe Windows x64 / Python 3.12, dacă folosești arhiva completă.

Pe alt Windows instalează Python 3.12 x64 cu Tcl/Tk și driverul CP210x, apoi rulează `Instaleaza.bat` și `Porneste.bat`. Arhiva nu include instalatorul Python sau driverul Windows. Pe acest PC aplicația este deja instalată.

Pentru Linux/GB10, codul nu depinde de DLL x86. Va necesita Python, Tk, `pyserial`, `svgelements`, NumPy pentru ARM64, permisiune pe portul serial și o nouă verificare hardware. **Rularea pe GB10 nu este încă testată.** Integrarea ComfyUI/FLUX este etapa următoare; mediul GB10 nu a fost modificat.

Teste: `.venv\Scripts\python.exe -m unittest discover -s tests -v`.

## Validare efectuată

Citirea USB și desenarea prin aplicația directă au fost testate pe robot de utilizator. Noul motor CP are teste simulate pentru preîncărcarea cozii, completarea în mers, bariera de final și anulare; nu a fost încă verificat fizic pe acest robot. Proba cu pixul ridicat rămâne disponibilă opțional. Calibrarea salvată este păstrată.

100 mm/s este viteza implicită, nu viteza mecanică maximă. Interfața nu impune un plafon numeric; controllerul trebuie să confirme viteza configurată. Marginea poate fi orice valoare nenegativă care lasă loc desenului; ridicarea poate fi zero sau pozitivă, iar corecția Z orice număr finit. Traseul trebuie să rămână în interiorul foii, la rezerva de 2 mm, și în limitele cinematice ale robotului. Accelerația CP este 100 mm/s²; curbele, colțurile și traseele scurte pot avea viteze efective mai mici. Nu se așteaptă confirmarea fiecărui punct înainte de trimiterea următorului.

Surse tehnice și licențe: `THIRD_PARTY.md`.


### Pornire cu pixul ridicat și suport cu arc

Z-ul salvat reprezintă poziția de desen cu arcul comprimat. Între linii, înălțimea de deplasare este Z-ul calibrat plus corecția Z plus ridicarea configurată. Poziția înaltă de pornire este păstrată separat pentru revenirea finală. Aplicația nu coboară la început lângă hârtie: merge ridicată până la primul traseu, apoi coboară vertical. Între trasee folosește ridicarea mică setată. La final se ridică vertical până la înălțimea de pornire (cel puțin înălțimea de deplasare), apoi revine deasupra punctului de pornire. Proba ridicată nu coboară niciodată la Z-ul de desen. Verificările de accesibilitate și de păstrare a traseului în interior rămân active.


Importul acceptă acum definiții defs neutilizate și stiluri CSS simple (clasă, ID sau element), inclusiv stiluri în defs. Geometria neutilizată din definiții nu este desenată. Referințele use, decupările, măștile și filtrele active necesită încă un export în trasee simple.


## Fotografie → SVG pe GB10

În aplicație, apasă **Poză → SVG pe GB10…**, alege o fotografie pătrată cu o persoană și introdu parola SSH. Conexiunea este `toni@100.111.144.112` prin Tailscale; calculatorul trebuie să aibă acces la această adresă. Parola este folosită în memorie, fără salvare. Cheia gazdei este verificată în fișierul OpenSSH `~/.ssh/known_hosts` (deja înregistrată pe acest PC).

Fotografia originală se transferă prin SFTP. Codul rulează în `/home/toni/dobot-portrait-client`, cu Python din `/home/toni/ComfyUI/.venv/bin/python`; ComfyUI rămâne pe `127.0.0.1:8188`. Modelele nu sunt instalate pe calculatorul robotului. Sursa GB10: https://github.com/tonihamza/sketch-robot-ai-dobot-magician-v2, commit a79eabafe720fd24dbab043a7541c60aba9c6cac.

Rezultatele se descarcă în `outputs/portrait-<id>/`: SVG, previzualizare PNG, rezultatul AI și jurnalul. SVG-ul se încarcă în previzualizare; robotul pornește numai după apăsarea separată a butonului DESENEAZĂ. Dacă foaia nu este calibrată, rezultatul rămâne încărcat până la calibrare. Fișierele de lucru rămân și în `jobs/` pe GB10.

STOP în timpul generării întrerupe clientul de generare prin SSH; o generare deja trimisă la ComfyUI poate continua pe server. Nu întrerupem alte joburi ComfyUI. Fotografiile care nu sunt pătrate sunt respinse de scriptul GB10, fără decupare automată.

Verificat: conexiune SSH, transfer SFTP în ambele sensuri, modelele și nodurile workflow-ului, cele două teste upstream pe GB10 și importul local al unui SVG vectorizat pe GB10 dintr-o imagine sintetică. Generarea completă Qwen dintr-o fotografie nu a fost rulată în această verificare. Nu s-au executat mișcări ale robotului.


### Modele rezidente și pași AI

GB10 folosește acum un override systemd pentru serviciul existent `hermes-comfyui.service`: `--highvram --cache-lru 32 --reserve-vram 16`. Modelele se încarcă la prima generare după pornirea serviciului și sunt păstrate în memorie/cache pentru reutilizare. Repornirea, golirea cache-ului sau alte workflow-uri care exercită presiune pe memorie pot necesita reîncărcare; nu este o promisiune de rezidență nelimitată. Nu există un serviciu separat care încarcă în paralel o a doua copie a modelelor.

Interfața are câmpul **Pași AI**, implicit 24. Poți selecta 40 pentru setarea anterioară sau 16/32 pentru alte compromisuri. Reducerea pașilor schimbă rezultatul și poate pierde detalii; nu este doar o optimizare a încărcării. Rezoluția și modelul Qwen rămân aceleași.

Conversia SVG de pe GB10 elimină legăturile diagonale redundante care fragmentau curbele pixelate, păstrează conexiunile scurte între ramuri și produce PNG-ul de previzualizare din traseele efectiv exportate. Importatorul robotului păstrează detalii până la 0,05 mm. Corecția nu inventează linii care lipsesc deja din imaginea AI.

Originalul scriptului de pe GB10 este păstrat în `generate_robot_portrait.py.before-continuity-fix`. Patch-ul pentru repository este salvat local în `reports/gb10-continuity.patch`; modificările sunt aplicate pe GB10, fără push automat pe GitHub. Override-ul este în `/home/toni/.config/systemd/user/hermes-comfyui.service.d/portrait-memory.conf`.


### Unirea fragmentelor apropiate

Câmpul **Unire capete (mm; 0 = oprit)** este implicit 0,3 mm, măsurați la dimensiunea finală pe hârtie. Unește capetele traseelor deschise cu diferență de direcție de cel mult 45°, dacă legătura continuă direcția liniilor (maximum 60° față de fiecare tangentă). Poate inversa fragmentele și extinde ambele capete. Contururile închise nu sunt conectate la alte trasee. Legătura este un segment drept desenat cu pixul jos; previzualizarea și execuția folosesc aceleași trasee. Numărul de uniri este afișat lângă numărul traseelor. Pragul nu identifică semantic liniile, deci verifică vizual rezultatul când îl mărești.

Logo de test: `examples/logo/laptop-aid-dobot-contur.svg`, reconstruit vectorial după captura furnizată, fără imagini încorporate sau text dependent de fonturi. Varianta `laptop-aid-logo.svg` are umpleri și culorile logo-ului; pentru robot folosește varianta contur. Pixul desenează ambele culori cu aceeași cerneală. Proporțiile orizontale sunt păstrate.


### Logo automat pe portrete

Opțiunea **Logo LAPTOP AID în stânga sus** este activă implicit și se aplică atât portretelor GB10, cât și SVG-urilor încărcate manual. Logo-ul are 40 mm lățime în zona normală de desen. Se rezervă o bandă superioară de 9 mm; portretul este micșorat proporțional și centrat dedesubt, fără suprapunere. Marginile setate sunt respectate. Pentru alte desene, inclusiv testul logo-ului singur, debifează opțiunea. Previzualizarea și execuția folosesc aceeași compoziție; SVG-ul original rămâne intact. Logo-ul se desenează cu aceeași cerneală ca portretul.


Logo-ul automat folosește acum `examples/logo/laptop-aid-o-singura-linie.svg`: litere cu trasee centrale simple, fără contururi duble. Traseele de sub 1 mm sunt eliminate după unirea fragmentelor și redimensionarea finală, înainte de planificarea mișcărilor. Filtrarea se aplică traseelor complete, nu segmentelor intermediare care descriu curbele. Previzualizarea arată exact traseele păstrate.


## Studio foto și cameră

Aplicația deschide automat o a doua fereastră, **LAPTOP AID · Cameră și portret**. Camera rămâne oprită până la **Fotografie nouă**. Poți muta această fereastră pe alt monitor și o poți redimensiona. Fereastra principală păstrează controlul robotului și o coloană de setări derulabilă.

- **Alege fotografie…** afișează un decupaj pătrat din centrul fotografiei. Fișierul original nu este modificat.
- **Fotografie nouă** pornește camera indicată de câmpul index (implicit 0). Se afișează doar pătratul central al cadrului, fără întindere și fără oglindire.
- **Pornește timerul · 5 secunde** afișează numărătoarea mare peste feed. La expirare se păstrează cel mai recent cadru; dacă feedul este învechit sau întrerupt, captura este anulată.
- **Salvează și generează** salvează fotografia pătrată în `captures/photo-<id>.png`, apoi pornește fluxul GB10. **Fă altă poză** reia captura.
- După generare, fereastra foto arată fotografia și portretul alăturat. Portretul este randat din aceleași trasee pregătite pentru robot, cu logo-ul și setările de filtrare/unire active. Alegerea unui SVG rămâne disponibilă și nu necesită camera.
- **DESENEAZĂ** pornește numai din fereastra principală, după conectarea și calibrarea robotului. AI-ul poate fi folosit și înainte de calibrare: previzualizarea folosește atunci o foaie virtuală de 80 × 80 mm, fără a crea o calibrare pentru robot.

Închiderea ferestrei foto oprește captura live; poate fi redeschisă cu **Arată fereastra foto**. Închiderea aplicației oprește camera. După o eroare de generare, fotografia rămâne disponibilă pentru reîncercare.

Aplicația rulează integral pe GB10 folosind AI-ul local, camera locală și robotul conectat la USB-ul GB10. Instalarea este descrisă în GB10.md. Pe Windows rămâne disponibilă generarea prin SSH.

Validare: 40 teste automate, inclusiv decupare, captură la cinci secunde, anulare la cadru învechit, confirmare înainte de generare și afișarea rezultatului fără pornire automată a robotului. Camera fizică index 0 a furnizat cadre de 480 × 480 după decupare, dar negre în proba efectuată; verifică obturatorul sau alt index. Generarea AI în noul flux a fost verificată cu răspuns simulat; backend-ul SSH/ComfyUI fusese verificat separat anterior. Nicio mișcare nouă a robotului nu a fost executată pentru această modificare.
