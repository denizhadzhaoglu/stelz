// Client-supplied "Influencers Lowlands tracking" list (STËLZ, Aug 2026).
// Kept in paste-format TSV so it flows through parseCreatorList exactly like
// any user paste — one code path, and the pre-flight test in importList.test.ts
// asserts the transcription parses clean (28 rows, 53 platform ids).
//
// Transcribed from the client's sheet; handles extracted from profile URLs,
// "?hl=…" tracking junk dropped. Three people have no TikTok ("Geen").
// Row 3's TikTok handle was hard to read in the source — verify on import.

export const LOWLANDS_SEED_NAME = 'Stelz Lowlands'

export const LOWLANDS_SEED = `Gasten	Tag Instagram	Tag TikTok
Stefan de Vries	stefandevries	stefandevries
Malith Yalage	heymalith	heymalith
Rein van Duivenboden	rvdofficial	rinnavandoffoe
Annekee	annekeemolenaar	Geen
Diego Bossers	diego.bossers	diegobossers
Frank Slotta	frankslotta	slottafrank
Lize Booij	lizebooij	booijagency
Daan Hoogervorst	daanhoogervorst	daandraaitdoorpodcast
Josh Bram	joshbram_	joshbram_
Pleun Bierbooms	pleunbierbooms	pleun.bierbooms
Sjoerd Kist	sjoerdkist	sjoerdkist
Karen Smit	karensmittt	karen.smit
Lizzy van der Ligt	lizzyvdligt	lizzyvdligt
Niek Roozen	niekroozen	niekroozen
Jitske Schaap	jitskeschaap	jitskeschaap
André Feulner	andref3000	Geen
Isadee Jansen	isadeejansen	isadeejans
Guusje Willemse	guusjewm	guusje.willemse
Sterre de Goede	sterredegoedex	sterredegoede
Noor Omrani	nooromrani	nooromrani
Daelorian	daelostylo	daelostylo
Talisia Misiedjan	talisia90	talisiamisiedjan
Eloise van Oranje	eloisevanoranje	eloisevoranje
Britt Messing	brittmessing	brittmessing
Tess Scholten	tessscholten	tessscholten
David Scholten	davidscholten	Geen
Jort Runia	jort_runia	jortruniajr
Gotu Jim	gotu_jim	gotu_jim`
