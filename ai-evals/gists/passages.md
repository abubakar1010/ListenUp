# Licensed passage selections

All ten are candidate edited excerpts from LibriSpeech test-clean, CC BY 4.0.
Attribution: LibriSpeech (c) 2014 Vassil Panayotov. Source readers and LibriVox
project IDs are in the manifest; these are public source credits, not learner IDs.
The [license copy](LIBRISPEECH-LICENSE.txt) is supplied. Credit the source, link
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and state the edits on
every redistribution. Source prose comes from public-domain audiobooks; check
local underlying-work rights before distribution in a new jurisdiction. The
corpus license does not claim to supersede rights in an underlying work.

| ID | Source/chapter | Speaker ID | Seconds |
| --- | --- | --- | ---: |
| p01 | Lectures on Landscape: Lecture III: Color | 1188 | 60.985 |
| p02 | Edison, His Life and Inventions: Other Early Stations -- the Meter | 2300 | 49.585 |
| p03 | Theory of the Leisure Class: 07 - Chapter IV - Conspicuous Consumption, Part One | 3570 | 47.400 |
| p04 | Analysis of Mind: 10 - MEMORY part 1 | 8230 | 59.915 |
| p05 | Gentle Measures in the Management and Training of the Young: 01 - Three Modes of Management | 7021 | 67.445 |
| p06 | Hoof and Claw: 10 - The Fisher in the Chutes | 7176 | 49.580 |
| p07 | Abraham Lincoln: A History (Volume 1): 25 - Civil War in Kansas | 7729 | 54.995 |
| p08 | Journey to the Interior of the Earth: Chapter 35 | 260 | 57.215 |
| p09 | Mother Careys Chickens: 27 - The Carey Housewarming | 4992 | 49.655 |
| p10 | Return of Sherlock Holmes: The Adventure of the Three Students, part 1 (p. 144) | 1580 | 49.990 |

## Provisioning and review

The [official source page](https://www.openslr.org/12/) identifies CC BY 4.0.
Download `test-clean.tar.gz` from the manifest archive URL. Extract only the
`parts[].archive_member` entries for a selection into an external source-assets
folder. Verify each SHA-256 and duration; concatenate decoded audio in the exact
listed order (16 kHz mono source FLAC, no inserted silence). For ffmpeg, put
the local file paths in a concat list and use `ffmpeg -f concat -safe 0 -i
parts.txt -c:a flac p01.flac`. Repeat per passage. Paths and transient signed
download URLs do not belong in the public dataset.

The manifest includes every selected segment’s actual corpus text, a joined
transcript, draft key points and the changes notice. These are real licensed
source texts, **not learner responses or teacher labels**. No learner recording
is required. Audio was downloaded for source integrity checks, with durations
measured by ffprobe; the human listening/suitability review remains pending.

LibriSpeech selections can omit original source sentences. Treat these as edited
excerpts, never contiguous original-book timestamps. Teachers must listen for
abrupt transitions and ambiguous referents, check transcript alignment and
correct/freeze the draft key points before anyone writes a response. In
particular, p05 and p06 need referent/continuity review; p03/p04/p07 have dense
or historical language. Replace a selection if it cannot stand alone. Pilot
comprehension/difficulty with consenting learners, then freeze or replace it;
do not silently change a reference after grading.

## Reading copies (teacher use only)

Do not show transcripts/key points to participants during Blind collection.

### p01 — Lectures on Landscape

YOU WILL FIND ME CONTINUALLY SPEAKING OF FOUR MEN TITIAN HOLBEIN TURNER AND TINTORET IN ALMOST THE SAME TERMS THEY UNITE EVERY QUALITY AND SOMETIMES YOU WILL FIND ME REFERRING TO THEM AS COLORISTS SOMETIMES AS CHIAROSCURISTS BY BEING STUDIOUS OF COLOR THEY ARE STUDIOUS OF DIVISION AND WHILE THE CHIAROSCURIST DEVOTES HIMSELF TO THE REPRESENTATION OF DEGREES OF FORCE IN ONE THING UNSEPARATED LIGHT THE COLORISTS HAVE FOR THEIR FUNCTION THE ATTAINMENT OF BEAUTY BY ARRANGEMENT OF THE DIVISIONS OF LIGHT MY FIRST AND PRINCIPAL REASON WAS THAT THEY ENFORCED BEYOND ALL RESISTANCE ON ANY STUDENT WHO MIGHT ATTEMPT TO COPY THEM THIS METHOD OF LAYING PORTIONS OF DISTINCT HUE SIDE BY SIDE SOME OF THE TOUCHES INDEED WHEN THE TINT HAS BEEN MIXED WITH MUCH WATER HAVE BEEN LAID IN LITTLE DROPS OR PONDS SO THAT THE PIGMENT MIGHT CRYSTALLIZE HARD AT THE EDGE

Draft points (awaiting teacher review):

- kp1 (main): The speaker explains how painters use colour and divisions of light.
- kp2 (supporting): Titian, Holbein, Turner and Tintoret are repeatedly discussed.
- kp3 (supporting): Colourists arrange divisions of light to achieve beauty.
- kp4 (supporting): Distinct hues are placed side by side.
- kp5 (supporting): Watery pigment can form hard edges.

### p02 — Edison, His Life and Inventions

THE PARIS PLANT LIKE THAT AT THE CRYSTAL PALACE WAS A TEMPORARY EXHIBIT THE LONDON PLANT WAS LESS TEMPORARY BUT NOT PERMANENT SUPPLYING BEFORE IT WAS TORN OUT NO FEWER THAN THREE THOUSAND LAMPS IN HOTELS CHURCHES STORES AND DWELLINGS IN THE VICINITY OF HOLBORN VIADUCT THERE MESSRS JOHNSON AND HAMMER PUT INTO PRACTICE MANY OF THE IDEAS NOW STANDARD IN THE ART AND SECURED MUCH USEFUL DATA FOR THE WORK IN NEW YORK OF WHICH THE STORY HAS JUST BEEN TOLD THE DYNAMO ELECTRIC MACHINE THOUGH SMALL WAS ROBUST FOR UNDER ALL THE VARYING SPEEDS OF WATER POWER AND THE VICISSITUDES OF THE PLANT TO WHICH IT BELONGED IT CONTINUED IN ACTIVE USE UNTIL EIGHTEEN NINETY NINE SEVENTEEN YEARS

Draft points (awaiting teacher review):

- kp1 (main): Early electric lighting plants helped develop practical technology.
- kp2 (supporting): The Paris and Crystal Palace plants were temporary exhibits.
- kp3 (supporting): The London plant supplied about three thousand lamps.
- kp4 (supporting): Johnson and Hammer gathered useful data for New York.
- kp5 (supporting): A small robust dynamo remained in use for seventeen years.

### p03 — Theory of the Leisure Class

BUT ALREADY AT A POINT IN ECONOMIC EVOLUTION FAR ANTEDATING THE EMERGENCE OF THE LADY SPECIALISED CONSUMPTION OF GOODS AS AN EVIDENCE OF PECUNIARY STRENGTH HAD BEGUN TO WORK OUT IN A MORE OR LESS ELABORATE SYSTEM THE UTILITY OF CONSUMPTION AS AN EVIDENCE OF WEALTH IS TO BE CLASSED AS A DERIVATIVE GROWTH SUCH CONSUMPTION AS FALLS TO THE WOMEN IS MERELY INCIDENTAL TO THEIR WORK IT IS A MEANS TO THEIR CONTINUED LABOUR AND NOT A CONSUMPTION DIRECTED TO THEIR OWN COMFORT AND FULNESS OF LIFE WITH A FURTHER ADVANCE IN CULTURE THIS TABU MAY CHANGE INTO SIMPLE CUSTOM OF A MORE OR LESS RIGOROUS CHARACTER BUT WHATEVER BE THE THEORETICAL BASIS OF THE DISTINCTION WHICH IS MAINTAINED WHETHER IT BE A TABU OR A LARGER CONVENTIONALITY THE FEATURES OF THE CONVENTIONAL SCHEME OF CONSUMPTION DO NOT CHANGE EASILY

Draft points (awaiting teacher review):

- kp1 (main): Consumption developed as a way to demonstrate wealth.
- kp2 (supporting): Specialised consumption predates the emergence of the lady.
- kp3 (supporting): Consumption assigned to women is described as supporting their labour.
- kp4 (supporting): A taboo can become a custom while consumption distinctions persist.

### p04 — Analysis of Mind

THE ANALYSIS OF KNOWLEDGE WILL OCCUPY US UNTIL THE END OF THE THIRTEENTH LECTURE AND IS THE MOST DIFFICULT PART OF OUR WHOLE ENTERPRISE WHAT IS CALLED PERCEPTION DIFFERS FROM SENSATION BY THE FACT THAT THE SENSATIONAL INGREDIENTS BRING UP HABITUAL ASSOCIATES IMAGES AND EXPECTATIONS OF THEIR USUAL CORRELATES ALL OF WHICH ARE SUBJECTIVELY INDISTINGUISHABLE FROM THE SENSATION WHETHER OR NOT THIS PRINCIPLE IS LIABLE TO EXCEPTIONS EVERYONE WOULD AGREE THAT IS HAS A BROAD MEASURE OF TRUTH THOUGH THE WORD EXACTLY MIGHT SEEM AN OVERSTATEMENT AND IT MIGHT SEEM MORE CORRECT TO SAY THAT IDEAS APPROXIMATELY REPRESENT IMPRESSIONS AND WHAT SORT OF EVIDENCE IS LOGICALLY POSSIBLE THERE IS NO LOGICAL IMPOSSIBILITY IN THE HYPOTHESIS THAT THE WORLD SPRANG INTO BEING FIVE MINUTES AGO EXACTLY AS IT THEN WAS WITH A POPULATION THAT REMEMBERED A WHOLLY UNREAL PAST

Draft points (awaiting teacher review):

- kp1 (main): The speaker examines perception, knowledge and the limits of evidence about memory.
- kp2 (supporting): Perception combines sensations with habitual images and expectations.
- kp3 (supporting): Ideas may approximately rather than exactly represent impressions.
- kp4 (supporting): A world created five minutes ago with false memories is presented as logically possible.

### p05 — Gentle Measures in the Management and Training of the Young

THE THREE MODES OF MANAGEMENT TO SUPPOSE THAT THE OBJECT OF THIS WORK IS TO AID IN EFFECTING SUCH A SUBSTITUTION AS THAT IS ENTIRELY TO MISTAKE ITS NATURE AND DESIGN BY REASON AND AFFECTION AS THE CHAISE DRIVES AWAY MARY STANDS BEWILDERED AND PERPLEXED ON THE DOOR STEP HER MIND IN A TUMULT OF EXCITEMENT IN WHICH HATRED OF THE DOCTOR DISTRUST AND SUSPICION OF HER MOTHER DISAPPOINTMENT VEXATION AND ILL HUMOR SURGE AND SWELL AMONG THOSE DELICATE ORGANIZATIONS ON WHICH THE STRUCTURE AND DEVELOPMENT OF THE SOUL SO CLOSELY DEPEND DOING PERHAPS AN IRREPARABLE INJURY THE MOTHER AS SOON AS THE CHAISE IS SO FAR TURNED THAT MARY CAN NO LONGER WATCH THE EXPRESSION OF HER COUNTENANCE GOES AWAY FROM THE DOOR WITH A SMILE OF COMPLACENCY AND SATISFACTION UPON HER FACE AT THE INGENUITY AND SUCCESS OF HER LITTLE ARTIFICE

Draft points (awaiting teacher review):

- kp1 (main): A mother deceives Mary and feels pleased while Mary is distressed.
- kp2 (supporting): Mary is left bewildered at the doorstep as a chaise leaves.
- kp3 (supporting): Mary feels distrust of her mother and hatred of the doctor.
- kp4 (supporting): The mother smiles once Mary cannot see her expression.

### p06 — Hoof and Claw

ALL ABOUT HIM WAS A TUMULT OF BRIGHT AND BROKEN COLOR SCATTERED IN BROAD SPLASHES THE MERGANSER HAD A CRESTED HEAD OF IRIDESCENT GREEN BLACK A BROAD COLLAR OF LUSTROUS WHITE BLACK BACK BLACK AND WHITE WINGS WHITE BELLY SIDES FINELY PENCILLED IN BLACK AND WHITE AND A BREAST OF RICH CHESTNUT RED STREAKED WITH BLACK HIS FEET WERE RED HIS LONG NARROW BEAK WITH ITS SAW TOOTHED EDGES AND SHARP HOOKED TIP WAS BRIGHT RED BUT HERE HE WAS AT A TERRIBLE DISADVANTAGE AS COMPARED WITH THE OWLS HAWKS AND EAGLES HE HAD NO RENDING CLAWS BUT SUDDENLY STRAIGHT AND SWIFT AS A DIVING CORMORANT HE SHOT DOWN INTO THE TORRENT AND DISAPPEARED BENEATH THE SURFACE ONCE FAIRLY A WING HOWEVER HE WHEELED AND MADE BACK HURRIEDLY FOR HIS PERCH

Draft points (awaiting teacher review):

- kp1 (main): Birds in a torrent are described through their appearance and actions.
- kp2 (supporting): The merganser has green-black, white and chestnut colouring.
- kp3 (supporting): Its red beak has saw-toothed edges and a hooked tip.
- kp4 (supporting): Lack of rending claws is a disadvantage compared with birds of prey.
- kp5 (supporting): A bird dives into the torrent and another movement returns toward a perch.

### p07 — Abraham Lincoln: A History (Volume 1)

THE BOGUS LEGISLATURE NUMBERED THIRTY SIX MEMBERS THIS WAS AT THE MARCH ELECTION EIGHTEEN FIFTY FIVE THAT SUMMER'S EMIGRATION HOWEVER BEING MAINLY FROM THE FREE STATES GREATLY CHANGED THE RELATIVE STRENGTH OF THE TWO PARTIES FOR GENERAL SERVICE THEREFORE REQUIRING NO SPECIAL EFFORT THE NUMERICAL STRENGTH OF THE FACTIONS WAS ABOUT EQUAL WHILE ON EXTRAORDINARY OCCASIONS THE TWO THOUSAND BORDER RUFFIAN RESERVE LYING A LITTLE FARTHER BACK FROM THE STATE LINE COULD AT ANY TIME EASILY TURN THE SCALE THE FREE STATE MEN HAD ONLY THEIR CONVICTIONS THEIR INTELLIGENCE THEIR COURAGE AND THE MORAL SUPPORT OF THE NORTH THE CONSPIRACY HAD ITS SECRET COMBINATION THE TERRITORIAL OFFICIALS THE LEGISLATURE THE BOGUS LAWS THE COURTS THE MILITIA OFFICERS THE PRESIDENT AND THE ARMY

Draft points (awaiting teacher review):

- kp1 (main): The passage describes the competing resources of Kansas political factions.
- kp2 (supporting): The legislature numbered thirty-six members.
- kp3 (supporting): Immigration from free states changed the balance of the parties.
- kp4 (supporting): A reserve of two thousand border ruffians could tip the balance.
- kp5 (supporting): The conspiracy had support from officials, laws, courts and the army.

### p08 — Journey to the Interior of the Earth

THE ROARINGS BECOME LOST IN THE DISTANCE THE WEATHER IF WE MAY USE THAT TERM WILL CHANGE BEFORE LONG THE ATMOSPHERE IS CHARGED WITH VAPOURS PERVADED WITH THE ELECTRICITY GENERATED BY THE EVAPORATION OF SALINE WATERS THE ELECTRIC LIGHT CAN SCARCELY PENETRATE THROUGH THE DENSE CURTAIN WHICH HAS DROPPED OVER THE THEATRE ON WHICH THE BATTLE OF THE ELEMENTS IS ABOUT TO BE WAGED THE AIR IS HEAVY THE SEA IS CALM FROM TIME TO TIME A FLEECY TUFT OF MIST WITH YET SOME GLEAMING LIGHT LEFT UPON IT DROPS DOWN UPON THE DENSE FLOOR OF GREY AND LOSES ITSELF IN THE OPAQUE AND IMPENETRABLE MASS THE ATMOSPHERE IS EVIDENTLY CHARGED AND SURCHARGED WITH ELECTRICITY THE WIND NEVER LULLS BUT TO ACQUIRE INCREASED STRENGTH THE VAST BANK OF HEAVY CLOUDS IS A HUGE RESERVOIR OF FEARFUL WINDY GUSTS AND RUSHING STORMS

Draft points (awaiting teacher review):

- kp1 (main): The narrator describes signs of an approaching powerful storm.
- kp2 (supporting): Evaporation of saline water is associated with vapour and electricity.
- kp3 (supporting): A dense curtain limits the electric light.
- kp4 (supporting): The air is heavy while the sea is calm.
- kp5 (supporting): The clouds hold dangerous gusts and storms.

### p09 — Mother Careys Chickens

NATTY HARMON TRIED THE KITCHEN PUMP SECRETLY SEVERAL TIMES DURING THE EVENING FOR THE WATER HAD TO RUN UP HILL ALL THE WAY FROM THE WELL TO THE KITCHEN SINK AND HE BELIEVED THIS TO BE A CONTINUAL MIRACLE THAT MIGHT GIVE OUT AT ANY MOMENT TO NIGHT THERE WAS NO NEED OF EXTRA HEAT AND THERE WERE GREAT CEREMONIES TO BE OBSERVED IN LIGHTING THE FIRES ON THE HEARTHSTONES THEY BEGAN WITH THE ONE IN THE FAMILY SITTING ROOM COLONEL WHEELER RALPH THURSTON MISTER AND MISSUS BILL HARMON WITH NATTY AND RUFUS MISTER AND MISSUS POPHAM WITH DIGBY AND LALLIE JOY ALL STANDING IN ADMIRING GROUPS AND THRILLING WITH DELIGHT AT THE ORDER OF EVENTS KATHLEEN WAVED THE TORCH TO AND FRO AS SHE RECITED SOME BEAUTIFUL LINES WRITTEN FOR SOME SUCH PURPOSE AS THAT WHICH CALLED THEM TOGETHER TO NIGHT

Draft points (awaiting teacher review):

- kp1 (main): A household celebrates by ceremonially lighting hearth fires.
- kp2 (supporting): Natty secretly tests the kitchen pump and marvels at water running uphill.
- kp3 (supporting): The first fire is in the family sitting room.
- kp4 (supporting): Families gather in admiration while Kathleen recites lines and waves a torch.

### p10 — Return of Sherlock Holmes

I WILL ENDEAVOUR IN MY STATEMENT TO AVOID SUCH TERMS AS WOULD SERVE TO LIMIT THE EVENTS TO ANY PARTICULAR PLACE OR GIVE A CLUE AS TO THE PEOPLE CONCERNED I HAD ALWAYS KNOWN HIM TO BE RESTLESS IN HIS MANNER BUT ON THIS PARTICULAR OCCASION HE WAS IN SUCH A STATE OF UNCONTROLLABLE AGITATION THAT IT WAS CLEAR SOMETHING VERY UNUSUAL HAD OCCURRED MY FRIEND'S TEMPER HAD NOT IMPROVED SINCE HE HAD BEEN DEPRIVED OF THE CONGENIAL SURROUNDINGS OF BAKER STREET WITHOUT HIS SCRAPBOOKS HIS CHEMICALS AND HIS HOMELY UNTIDINESS HE WAS AN UNCOMFORTABLE MAN I HAD TO READ IT OVER CAREFULLY AS THE TEXT MUST BE ABSOLUTELY CORRECT I WAS ABSENT RATHER MORE THAN AN HOUR THE ONLY DUPLICATE WHICH EXISTED SO FAR AS I KNEW WAS THAT WHICH BELONGED TO MY SERVANT BANNISTER A MAN WHO HAS LOOKED AFTER MY ROOM FOR TEN YEARS AND WHOSE HONESTY IS ABSOLUTELY ABOVE SUSPICION

Draft points (awaiting teacher review):

- kp1 (main): A narrator conceals identities while recounting an unusual and troubling incident.
- kp2 (supporting): A man is unusually agitated.
- kp3 (supporting): The narrator’s friend is uncomfortable away from Baker Street.
- kp4 (supporting): A text needs careful checking for correctness.
- kp5 (supporting): Bannister has a duplicate and is described as an honest long-serving servant.
