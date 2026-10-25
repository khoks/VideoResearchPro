"""S-1.18.9: the deterministic attribution guard for visual annotations.

Every fixture reproduces a confirmed R1 error (docs/notes/2026-10-18-r1-visual-measurement.md)
on synthetic transcripts that go through the production span format
(`annotate_segments` -> `chunk_transcript`). The guard must:

- mark a detail found only in an on-screen span when a sentence credits it to
  a speaker (run 8's weekday totals; run 1's confidence band; run 6's light
  grid, which the speaker said elsewhere in the video but not at that moment);
- write "not spoken" only for a figure absent from Latin-script speech, never
  for Bengali or Devanagari speech, where an absence proves nothing;
- correct speech presented as screen (run 3) and drop an "also visible on
  screen" whose frame belongs to another video (run 6);
- leave alone what is already right: spoken figures, sentences that put the
  detail on screen themselves, neutral statements, code arguments.

Run 9's follow-ups: a lone screen figure among the speaker's spoken examples
("his examples are 10, 15,000, 0 and 1"), a quote's transliteration read as
quotation, and the "also" in "also visible on screen" dropped when the speaker
did not say the detail.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.prompts.shared import MODALITY_BOTH, MODALITY_SAID, MODALITY_SHOWN
from app.services import attribution_guard as ag
from app.services.visual_service import annotate_segments
from app.utils.chunking import chunk_transcript


@dataclass
class _Frame:
    timestamp_seconds: float
    description: str
    informative: bool = True
    status: str = "described"


def _source(video_id: str, title: str, channel: str, segments: list[tuple[float, str]],
            frames: list[tuple[float, str]] = ()) -> list[dict]:
    segs = [{"text": t, "start": s, "duration": 8.0} for s, t in segments]
    segs = annotate_segments(segs, [_Frame(s, d) for s, d in frames])
    return chunk_transcript(segs, chunk_size=256, chunk_overlap=32, video_metadata={
        "video_id": video_id, "title": title, "channel_name": channel,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    })


def _link(video_id: str, seconds: int, label: str) -> str:
    return f'<a href="https://www.youtube.com/watch?v={video_id}&t={seconds}" target="_blank">{label}</a>'


TOTALS = ("Mon 1 17363.10; Tue 2 18158.38; Wed 3 15750.46; Thu 4 16091.40; "
          "Fri 5 16802.66; Sat 6 14733.52; Sun 7 13336.06")
COFFEE_SPEECH = [
    (1039.0, "Now let's look at our sales by weekday."),
    (1050.0, "So you'll see here we have our weekday, we have our sort order, and we have the total "
             "amount spent on that weekday across all of the data."),
    (1066.0, "We had 3,000 transactions in this file."),
    (1100.0, "Let's sort it so that Monday comes first."),
    (1112.0, "And you can see Tuesday is generally our best sales day."),
]
COFFEE_FRAME = (1104.0, f"A Jupyter notebook cell shows `day_totals` with rows: {TOTALS}.")
RUN8_SENTENCE = (
    "<p>The exceptions are instructive: Data Analytics Lab reads a coffee-sales dataset to a full "
    "analytical story — a 10:00 a.m. rush with an afternoon pickup, and Tuesday as the strongest "
    "sales day (Monday 17,363.10; Tuesday 18,158.38; Wednesday 15,750.46; Thursday 16,091.40; "
    "Friday 16,802.66; Saturday 14,733.52; Sunday 13,336.06) — and models interpretation as an "
    "argument with one's own expectations.</p>"
)


def _coffee(speech=COFFEE_SPEECH, frames=(COFFEE_FRAME,)) -> list[dict]:
    return _source("OEWAgzYv2mE", "Seaborn Python Tutorial: How to Analyze Data", "Data Analytics Lab",
                   speech, frames)


def _evidence(*sources: list[dict], speakers=()) -> ag.Evidence:
    return ag.build_evidence([c for chunks in sources for c in chunks], speakers)


# ---------- speaker-credited screen details ----------------------------------

def test_run8_weekday_totals_in_a_speaker_credited_sentence_are_marked_on_screen():
    html, rewrites = ag.guard_report(RUN8_SENTENCE, _evidence(_coffee()))
    assert ("sales day (on screen at 18:24, not spoken: Monday 17,363.10; Tuesday 18,158.38; Wednesday "
            "15,750.46; Thursday 16,091.40; Friday 16,802.66; Saturday 14,733.52; Sunday 13,336.06)") in html
    assert [r.kind for r in rewrites] == ["screen_detail_marked"]
    assert rewrites[0].verified and rewrites[0].seconds == 1104.0 and len(rewrites[0].tokens) == 7
    # Substance moves, it is not lost: every figure is still there.
    for figure in ("17,363.10", "13,336.06"):
        assert figure in html


def test_figures_the_speaker_says_are_left_alone():
    spoken = COFFEE_SPEECH + [(1120.0, "Monday is 17,363.10, Tuesday 18,158.38, Wednesday 15,750.46, "
                                       "Thursday 16,091.40, Friday 16,802.66, Saturday 14,733.52 and "
                                       "Sunday 13,336.06.")]
    html, rewrites = ag.guard_report(RUN8_SENTENCE, _evidence(_coffee(spoken)))
    assert html == RUN8_SENTENCE and rewrites == []


def test_a_sentence_that_already_puts_the_figures_on_screen_is_left_alone():
    html = (f"<p>The displayed table shows Monday 17,363.10 and Tuesday 18,158.38 — Data Analytics Lab "
            f"({_link('OEWAgzYv2mE', 1039, '17:19')}).</p>")
    assert ag.guard_report(html, _evidence(_coffee())) == (html, [])


def test_a_neutral_statement_is_left_alone():
    """No speaker is credited: a figure with a citation link is not an attribution error."""
    html = (f"<p>Weekday totals in the heat-map example are Monday 17,363.10; Tuesday 18,158.38 "
            f"({_link('OEWAgzYv2mE', 1039, '17:19')}).</p>")
    assert ag.guard_report(html, _evidence(_coffee())) == (html, [])


def _onur() -> list[dict]:
    return _source("I1Hsa9TSO5U", "Seaborn Course: Learn Data Visualization", "Onur Baltaci",
                   [(621.0, "A regression plot shows the relationship between two numerical variables "
                            "with a fitted line."), (660.0, "Let's run it.")],
                   [(674.0, "The regression plot uses Value1 on the x-axis and Value2 on the y-axis, "
                            "an upward-sloping fitted line with a light-blue confidence band.")])


def test_a_clause_ending_in_a_name_credits_that_speaker_run1():
    html = ("<li>A regression plot displays two numerical variables, a fitted regression line, and a "
            "confidence band to help assess a linear relationship — Onur Baltaci "
            f"({_link('I1Hsa9TSO5U', 621, '10:21')}).</li>")
    out, rewrites = ag.guard_report(html, _evidence(_onur()))
    assert "a confidence band (on screen at 11:14) to help assess" in out
    # A descriptor pair is never "not spoken": its absence from speech is weak evidence.
    assert "not spoken" not in out and not rewrites[0].verified


def test_screen_only_is_decided_near_the_cited_moment_run6():
    """The presenter said "light grid lines" at 9:00; the 22:28 sentence took "light grid" from the 22:33 frame."""
    # Twelve minutes of other talk in between, so 9:00 and 22:28 land in different chunks.
    filler = [(600.0 + 60 * k, "then we format the dates, rotate the tick labels, set the figure size and "
                               "the title, and check how the store sales compare across the months of the "
                               "year before moving on to the next chart in this part of the tutorial "
                               "where we look at bar charts and scatter plots of the same data.")
              for k in range(11)]
    style = _source("50SGBO3Psqk", "Matplotlib Tutorial for Beginners", "Style Lab",
                    [(540.0, "we'll also add some like light grid lines in here to make it readable."),
                     *filler,
                     (1304.0, "so I like the 538 style, I'll specify it to 538."),
                     (1340.0, "you'll see we have kind of a different style than we had before.")],
                    [(1353.0, "the chart uses a light gray grid/538-like style with a blue line.")])
    html = (f"<p>He likes the fivethirtyeight style ({_link('50SGBO3Psqk', 1304, '21:44')}), describing "
            f"the 538-like result as a different-looking chart with a light grid "
            f"({_link('50SGBO3Psqk', 1348, '22:28')}).</p>")
    out, rewrites = ag.guard_report(html, _evidence(style))
    assert "with a light grid (on screen at 22:33) (" in out
    # Said elsewhere in the video, so the mark never claims it was not spoken.
    assert "not spoken" not in out
    assert [r.tokens for r in rewrites] == [["light grid"]]


def test_not_spoken_is_never_claimed_for_bengali_speech():
    munna = _source("5AuuOZ4vuxI", "01. Seaborn in Python", "CodeWithMunnaX",
                    [(596.0, "এখানে অনেক ডেটাসেট আছে, আমরা এগুলো ব্যবহার করতে পারি।"),
                     (640.0, "এখন আমরা টাইটানিক লোড করব।")],
                    [(613.0, "Output of sns.get_dataset_names(): ['anagrams', 'dowjones', 'fmri', "
                             "'geyser', 'iris', 'seaice']. A dataframe below reports 891 rows.")])
    html = (f"<p>CodeWithMunnaX lists dowjones, fmri, geyser and seaice among the available datasets and "
            f"says the Titanic data has 891 rows ({_link('5AuuOZ4vuxI', 596, '9:56')}).</p>")
    out, rewrites = ag.guard_report(html, _evidence(munna))
    assert "dowjones, fmri, geyser and seaice (on screen at 10:13) among" in out
    assert "891 (on screen at 10:13) rows" in out
    assert "not spoken" not in out and not any(r.verified for r in rewrites)


def test_spoken_numbers_read_words_and_caption_habits():
    speech = ag._norm_speech("it's a 15 000 row data set, about fifteen thousand rows; enter one two two; "
                             "a correlation of point nine two; seventeen thousand three hundred sixty three "
                             "point one; and set alpha to point4")
    found = ag._spoken_numbers(speech)
    assert {"15000", "122", "0.92", "17363.1", "0.4"} <= found


DEEPLOOP_SPEECH = [
    (964.0, "और एक ही ऐसी वैल्यू है जो है 1024 या फिर है 15,000। ठीक है? तो यह बहुत ही ज्यादा रेंज के "
            "बाहर आ गया। या फिर एक ऐसी वैल्यू है जो है 0 या फिर वन।"),
    (1028.0, "लोअर आउटलाइन ये हमारा है यहां पे 50% ये 25% ये 75% ठीक है?"),
    (1040.0, "मीडियन यहां पे ये हमारा बॉक्स प्लॉट।"),
]
DEEPLOOP_FRAME = (1034.0, "A OneNote page titled “Seaborn” shows handwritten notes under “Box Plot”: "
                          "“median,” “Quartely -> 25%, 75%, 50%” and “outliers -> 25 - 75 | 10% | 15%”.")
RUN9_SENTENCE = ("<li>Values far outside the 25%–75% range — his examples are 10, 15,000, 0 and 1 — count as "
                 f"outliers ({_link('6lgc8xPTDS0', 964, '16:04')}).</li>")


def _deeploop(speech=DEEPLOOP_SPEECH) -> list[dict]:
    return _source("6lgc8xPTDS0", "Seaborn Tutorial in Hindi", "DeepLoop Circle", speech, [DEEPLOOP_FRAME])


def test_a_lone_screen_figure_among_spoken_examples_is_marked_run9():
    """Run 9's error: the speaker said 1024, 15,000, 0 and 1; the 10 is the handwritten "10%".

    "His examples" credits the speaker without a speech verb. A lone two-digit
    figure is acted on only inside a list whose other figures the speaker said.
    """
    out, rewrites = ag.guard_report(RUN9_SENTENCE, _evidence(_deeploop(), speakers=["Vivek"]))
    assert "his examples are 10 (on screen at 17:14), 15,000, 0 and 1 — count" in out
    assert [r.tokens for r in rewrites] == [["10"]]
    assert "not spoken" not in out and not rewrites[0].verified      # Devanagari speech proves nothing


def test_a_lone_figure_without_a_spoken_list_keeps_the_threshold():
    # The other figures in words the guard cannot read: nothing anchors the list.
    words = [(964.0, "और एक ही ऐसी वैल्यू है जो है एक हजार चौबीस या फिर है पंद्रह हजार। या फिर एक ऐसी "
                     "वैल्यू है जो है 0 या फिर वन।"), *DEEPLOOP_SPEECH[1:]]
    assert ag.guard_report(RUN9_SENTENCE, _evidence(_deeploop(words))) == (RUN9_SENTENCE, [])
    alone = f"<li>His example of an outlier is 10 ({_link('6lgc8xPTDS0', 964, '16:04')}).</li>"
    assert ag.guard_report(alone, _evidence(_deeploop())) == (alone, [])
    # A spoken list elsewhere in the sentence does not vouch for a figure outside it.
    apart = (f"<li>His examples are 1024, 15,000, 0 and 1, and he puts the cut-off at 10 "
             f"({_link('6lgc8xPTDS0', 964, '16:04')}).</li>")
    assert ag.guard_report(apart, _evidence(_deeploop())) == (apart, [])


def test_the_run9_map_item_lists_its_lone_screen_figure():
    """The map stage wrote run 9's error first, labelled `said`."""
    item = {"content": "Values far outside the quartile range count as outliers, such as 10, 15,000, 0, or 1 "
                       "in the speaker's examples.", "video_title": "Seaborn Tutorial in Hindi",
            "channel_name": "DeepLoop Circle", "timestamp_display": "16:04–16:19", "timestamp_seconds": 964,
            "video_url": "https://www.youtube.com/watch?v=6lgc8xPTDS0&t=964", "modality": MODALITY_SAID}
    summary = {"facts": [item]}
    ag.label_items(summary, _evidence(_deeploop()))
    assert item["modality"] == MODALITY_BOTH and item["screen_only"] == ["10"]


# ---------- the converse: speech presented as screen ---------------------------

def _munna_version() -> list[dict]:
    return _source("5AuuOZ4vuxI", "01. Seaborn in Python", "CodeWithMunnaX",
                   [(177.0, "আপনার আউটপুট স্ক্রিনে এভাবে আসবে: ০.১৩.২।"),
                    (190.0, "আপনার ক্ষেত্রে অন্য ভার্সনও আসতে পারে।")],
                   [(400.0, "A notebook cell imports seaborn as sns and matplotlib.pyplot as plt.")])


def _simplilearn_version() -> list[dict]:
    return _source("Fnn7rCrN_88", "Seaborn Tutorial For Beginners", "Simplilearn",
                   [(160.0, "let's check which version we have installed.")],
                   [(174.0, "The notebook prints the seaborn version 0.13.2 below the import cell.")])


def test_also_visible_on_screen_with_another_videos_frame_is_removed_run6():
    html = (f"<li>As of this tutorial, the presenter says the printed Seaborn version is 0.13.2 — "
            f"CodeWithMunnaX ({_link('5AuuOZ4vuxI', 177, '02:57')}). The output was also visible on screen.</li>")
    out, rewrites = ag.guard_report(html, _evidence(_munna_version(), _simplilearn_version()))
    assert "also visible on screen" not in out
    assert "the printed Seaborn version is 0.13.2 — CodeWithMunnaX" in out
    assert [r.kind for r in rewrites] == ["screen_claim_removed"]


def test_the_video_displays_a_figure_only_spoken_is_marked_as_said_run3():
    html = "<p>On version pinning, the video displays Seaborn version 0.13.2 at 03:10 — 01. Seaborn in Python — CodeWithMunnaX.</p>"
    out, rewrites = ag.guard_report(html, _evidence(_munna_version(), _simplilearn_version()))
    assert "version 0.13.2 (said at 2:57; no captured frame shows it) at 03:10" in out
    assert [r.kind for r in rewrites] == ["speech_as_screen_marked"]


def test_a_quotes_transliteration_is_quotation_run9():
    """Run 9 put a second "(said at ...)" inside the romanised transliteration of a Bengali quote."""
    quote = ("আপনার আউটপুট স্ক্রিনে এভাবে আসবে: ০.১৩.২। (āpnār output screen-e ebhābe āsbe: 0.13.2.) — "
             '"your output will show like this: 0.13.2"')
    html = (f"<p>The CodeWithMunnaX presenter states the displayed Seaborn version is 0.13.2: {quote} "
            f"({_link('5AuuOZ4vuxI', 177, '2:57')}).</p>")
    out, rewrites = ag.guard_report(html, _evidence(_munna_version(), _simplilearn_version()))
    assert "version is 0.13.2 (said at 2:57; no captured frame shows it): " + quote in out
    assert [r.kind for r in rewrites] == ["speech_as_screen_marked"]


def test_a_frame_backed_claim_stays_and_loses_also_when_the_figure_was_not_said():
    html = (f"<p>The Simplilearn presenter checks the installed version, 0.13.2, also visible on screen "
            f"({_link('Fnn7rCrN_88', 160, '2:40')}).</p>")
    out, rewrites = ag.guard_report(html, _evidence(_simplilearn_version()))
    assert "the installed version, 0.13.2, visible on screen (" in out
    assert [r.kind for r in rewrites] == ["screen_also_dropped"]


def test_also_visible_stays_when_the_speaker_said_it_too():
    said = _source("Fnn7rCrN_88", "Seaborn Tutorial For Beginners", "Simplilearn",
                   [(160.0, "let's check which version we have installed. It says 0.13.2.")],
                   [(174.0, "The notebook prints the seaborn version 0.13.2 below the import cell.")])
    html = (f"<p>The Simplilearn presenter checks the installed version, 0.13.2, also visible on screen "
            f"({_link('Fnn7rCrN_88', 160, '2:40')}).</p>")
    assert ag.guard_report(html, _evidence(said)) == (html, [])


def test_also_goes_after_a_marked_screen_only_detail_run9():
    """Run 9: after the guard's mark, the composer's "is also visible on screen" still implied speech."""
    html = ("<li>A regression plot shows two numerical variables, a fitted regression line and a confidence "
            f"band, helping assess linear relationships — Onur Baltaci ({_link('I1Hsa9TSO5U', 621, '10:21')}); "
            "the confidence band is also visible on screen.</li>")
    out, rewrites = ag.guard_report(html, _evidence(_onur()))
    assert "and a confidence band (on screen at 11:14), helping" in out
    assert "the confidence band is visible on screen.</li>" in out
    assert [r.kind for r in rewrites] == ["screen_detail_marked", "screen_also_dropped"]


# ---------- what is never touched --------------------------------------------

def test_code_arguments_are_never_split():
    aca = _source("qErBw-R2Ybk", "Python - Matplotlib Tutorial for Beginners", "Academind",
                  [(865.0, "now we add chart one with add subplot and enter one two one."),
                   (900.0, "and chart two, i'll enter one two two.")],
                  [(927.0, "Two code cells: fig.add_subplot(121) and fig.add_subplot(122); a notebook "
                           "shows sns.lineplot(x=x, y=y) and MaxNLocator(integer=True).")])
    html = (f"<p>The presenter adds fig.add_subplot(121) and fig.add_subplot(122), calls "
            f"<code>sns.lineplot(x=x, y=y)</code> and uses <code>MaxNLocator(integer=True)</code> — Academind "
            f"({_link('qErBw-R2Ybk', 865, '14:25')}).</p>")
    out, _ = ag.guard_report(html, _evidence(aca))
    for code in ("fig.add_subplot(121)", "fig.add_subplot(122)", "<code>sns.lineplot(x=x, y=y)</code>",
                 "<code>MaxNLocator(integer=True)</code>"):
        assert code in out
    # Any mark lands after the code, outside the tag.
    assert "(on screen" not in out.split("<code>")[1].split("</code>")[0]


def test_a_corpus_without_spans_is_untouched():
    plain = _source("OEWAgzYv2mE", "Seaborn Python Tutorial", "Data Analytics Lab", COFFEE_SPEECH)
    evidence = _evidence(plain)
    assert not evidence.has_visual
    assert ag.guard_report(RUN8_SENTENCE, evidence) == (RUN8_SENTENCE, [])


def test_links_and_tags_survive_a_rewrite():
    html = (f"<p><strong>Data Analytics Lab</strong> reads the totals as Monday 17,363.10 and "
            f"Tuesday 18,158.38 ({_link('OEWAgzYv2mE', 1039, '17:19')}).</p>")
    out, rewrites = ag.guard_report(html, _evidence(_coffee()))
    assert rewrites
    assert _link("OEWAgzYv2mE", 1039, "17:19") in out
    assert out.startswith("<p><strong>Data Analytics Lab</strong> reads") and out.endswith("</p>")
    assert "Tuesday 18,158.38 (on screen at 18:24, not spoken) (" in out


# ---------- map items --------------------------------------------------------

COFFEE_URL = "https://www.youtube.com/watch?v=OEWAgzYv2mE"


def _item(content: str, modality: str, display: str = "17:19–18:24", **extra) -> dict:
    item = {"content": content, "video_title": "Seaborn Python Tutorial: How to Analyze Data",
            "channel_name": "Data Analytics Lab", "timestamp_display": display,
            "timestamp_seconds": 1039, "video_url": f"{COFFEE_URL}&t=1039", "speaker": "Presenter",
            "modality": modality}
    item.update(extra)
    return item


def test_an_item_whose_figures_are_all_on_screen_becomes_shown():
    """Run 8: the weekday totals reached compose tagged [SAID+SHOWN]."""
    summary = {"facts": [_item("The weekday totals in the heat-map example are Monday 17,363.10; Tuesday "
                               "18,158.38; Wednesday 15,750.46; and Sunday 13,336.06.", MODALITY_BOTH)]}
    counts: dict = {}
    ag.label_items(summary, _evidence(_coffee()), counts)
    item = summary["facts"][0]
    assert item["modality"] == MODALITY_SHOWN and item["modality_before_guard"] == MODALITY_BOTH
    assert counts == {"relabelled_shown": 1}


def test_an_item_mixing_spoken_and_screen_only_clauses_is_split():
    summary = {"facts": [_item("The file holds 3,000 transactions; the weekday totals are Monday 17,363.10 "
                               "and Tuesday 18,158.38.", MODALITY_BOTH)]}
    counts: dict = {}
    ag.label_items(summary, _evidence(_coffee()), counts)
    kept, shown = summary["facts"]
    assert kept["content"] == "The file holds 3,000 transactions" and kept["modality"] == MODALITY_BOTH
    assert shown["content"] == "the weekday totals are Monday 17,363.10 and Tuesday 18,158.38."
    assert shown["modality"] == MODALITY_SHOWN and shown["split_by_guard"] and "speaker" not in shown
    assert counts == {"split": 1}


def test_bengali_speech_is_never_relabelled_only_listed():
    munna = _source("5AuuOZ4vuxI", "01. Seaborn in Python", "CodeWithMunnaX",
                    [(596.0, "এখানে অনেক ডেটাসেট আছে।")],
                    [(613.0, "A dataframe reports 891 rows and 12 columns.")])
    item = {"content": "The Titanic data has 891 rows.", "video_title": "01. Seaborn in Python",
            "channel_name": "CodeWithMunnaX", "timestamp_display": "9:56–10:20", "timestamp_seconds": 596,
            "video_url": "https://www.youtube.com/watch?v=5AuuOZ4vuxI&t=596", "modality": MODALITY_SAID}
    summary = {"facts": [item]}
    ag.label_items(summary, _evidence(munna))
    assert item["modality"] == MODALITY_BOTH and item["screen_only"] == ["891"]
    assert item["modality_before_guard"] == MODALITY_SAID


def test_an_item_with_a_verified_original_quote_is_listed_not_relabelled():
    item = _item("Monday 17,363.10 and Tuesday 18,158.38 are the totals.", MODALITY_BOTH,
                 original="the total amount spent on that weekday")
    summary = {"facts": [item]}
    ag.label_items(summary, _evidence(_coffee()))
    assert item["modality"] == MODALITY_BOTH and item["screen_only"] == ["17,363.10", "18,158.38"]


def test_items_without_screen_evidence_are_untouched():
    plain_item = _item("Tuesday is generally the best sales day.", MODALITY_SAID)
    shown_item = _item("The table shows Monday 17,363.10.", MODALITY_SHOWN)
    summary = {"facts": [plain_item, shown_item]}
    before = [dict(plain_item), dict(shown_item)]
    ag.label_items(summary, _evidence(_coffee()))
    assert summary["facts"] == before
    # And nothing at all happens for a corpus with no span.
    summary2 = {"facts": [_item("Monday 17,363.10 and Tuesday 18,158.38.", MODALITY_BOTH)]}
    plain = _source("OEWAgzYv2mE", "Seaborn Python Tutorial: How to Analyze Data", "Data Analytics Lab",
                    COFFEE_SPEECH)
    ag.label_items(summary2, _evidence(plain))
    assert summary2["facts"][0]["modality"] == MODALITY_BOTH and "screen_only" not in summary2["facts"][0]
