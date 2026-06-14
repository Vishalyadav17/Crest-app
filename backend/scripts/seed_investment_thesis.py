"""
Seed InvestmentThesis rows from research memory files (source: research_2026).

Run: .venv/bin/python -m scripts.seed_investment_thesis [user_id]
Idempotent — upserts by (user, asset_type, sym).
conviction: 5=Tier1, 4=Tier2, 3=swing/watchlist
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone

from database import SessionLocal
from models import InvestmentThesis

THESES = [
    dict(
        sym="CCL", name="CCL Products",
        why_holding=(
            "World's largest private label instant coffee manufacturer with B2B contracts to JDE, Reliance, and 100+ countries. "
            "No new capex planned for 3 years — capacity sufficient through FY27. "
            "B2C Continental Coffee brand creates re-rating optionality as premium coffee grows in India."
        ),
        entry_trigger="Dip to ₹950-1050 ideal zone; B2C revenue share crossing 15% a signal.",
        exit_trigger="Large unplanned capex announcement, B2C brand fails to gain traction, Vietnam plant utilisation drops.",
        conviction=5,
    ),
    dict(
        sym="QPOWER", name="Quality Power Electrical Equipment",
        why_holding=(
            "India's only approved HVDC/STATCOM/reactor supplier — 7-8 year regulatory moat via type-testing requirements. "
            "Sangli plant 9x capacity expansion live Q1 FY27, timed for India's ₹9 lakh cr grid investment cycle. "
            "FY26 revenue ₹1,007 cr was a massive beat; order book visibility is high."
        ),
        entry_trigger="Q1 FY27 Sangli ramp confirmation; entry ₹950-1050.",
        exit_trigger="PGCIL/HVDC approvals opened to new competitors, Sangli ramp disappoints, promoter exits.",
        conviction=5,
    ),
    dict(
        sym="HBLENGINE", name="HBL Power Systems",
        why_holding=(
            "Kavach train collision-avoidance system — 30% market share with 70,000 km railway coverage target by 2028. "
            "Debt-free balance sheet with clean cash generation from batteries segment funding growth. "
            "Electric trucks and Tonbo Imaging stake provide long-duration optionality."
        ),
        entry_trigger="Kavach order conversion rate; quarterly execution vs guidance; entry ₹580-650.",
        exit_trigger="Kavach program delayed or scope reduced, battery business margin structural decline, Tonbo Imaging losses mount.",
        conviction=5,
    ),
    dict(
        sym="GRSE", name="Garden Reach Shipbuilders",
        why_holding=(
            "India's largest listed defence shipbuilder — ₹21,700 cr order book providing 3-4 year revenue visibility. "
            "43% ROCE with zero debt; structural advantage from advance payments earning interest income. "
            "Naval indigenisation mandate from GoI makes this a long-duration compounder."
        ),
        entry_trigger="New frigate/corvette order wins; entry ₹2,000-2,400.",
        exit_trigger="Defence capex cuts, shipyard execution failure on P17A frigates, order book depletion without replacement.",
        conviction=5,
    ),
    dict(
        sym="GRAVITA", name="Gravita India",
        why_holding=(
            "India's largest organised multi-material recycler — EPR mandate makes battery recycling structurally mandatory. "
            "RMI acquisition expected to double revenue in FY27 while entering rubber recycling. "
            "International presence (8 countries) provides FX revenue diversification."
        ),
        entry_trigger="RMI integration tracking, EPR certificate volumes; entry ₹1,200-1,350.",
        exit_trigger="EPR Battery Waste rules rolled back, commodity lead price crash sustained >6 months, RMI integration fails.",
        conviction=4,
    ),
    dict(
        sym="PICCADIL", name="Piccadily Agro Industries",
        why_holding=(
            "Indri single malt whisky — named Best Whisky In The World, sold in 28+ countries. "
            "Mahasamund 2.3x capacity expansion live FY26 to meet surging international demand. "
            "Camikara rum provides a second premium brand; sugar demerger is an optionality catalyst."
        ),
        entry_trigger="IMFL volume trajectory in Q1/Q2 FY27, sugar demerger announcement; entry ₹450-550.",
        exit_trigger="Brand damage (counterfeits, quality scandal), capacity underutilisation after ramp, promoter dilution.",
        conviction=5,
    ),
    dict(
        sym="KWALITY", name="Kwality Pharmaceuticals",
        why_holding=(
            "Pure B2B injectable exporter — EU-GMP approvals on 4 of 5 units create a high regulatory moat. "
            "Biologics entry via Unit 5 positions the company for the next growth S-curve. "
            "Tiny float of 1.04 cr shares creates high price velocity on positive catalysts."
        ),
        entry_trigger="Unit 5 EU-GMP approval, biologics NDA filing, revenue guidance upgrade; entry ₹1,900-2,100.",
        exit_trigger="EU-GMP revocation on any unit, key export market regulatory failure, float expansion via promoter exit.",
        conviction=5,
    ),
    dict(
        sym="CARTRADE", name="CarTrade Tech",
        why_holding=(
            "Auto classifieds platform with 95% organic traffic plus SAMIL (India's largest auto repossession auctioneer) and OLX India. "
            "₹1,244 cr cash on books = nearly half of market cap, with ₹1,000 cr PAT aspiration by FY28. "
            "FY26 PAT ₹243 cr (+68%) demonstrates operating leverage kicking in."
        ),
        entry_trigger="OLX India profitability milestone, SAMIL market share gains; entry ₹1,800-2,000.",
        exit_trigger="Promoter (Temasek/IIFL) stake sale creating sustained overhang, CarWale loses OEM ad contracts to Meta/Google.",
        conviction=4,
    ),
    dict(
        sym="APOLLO", name="Apollo Micro Systems",
        why_holding=(
            "Mission-critical defence electronics for DRDO — ~63% of electronics in all DRDO missile programs. "
            "Project Kusha (India's S-400) subsystems delivery Sep 2026; order book ₹3,905 cr as of Q4 FY26. "
            "Moving from subsystem supplier to Tier-1 OEM increases addressable revenue per contract."
        ),
        entry_trigger="Pledge resolution confirmed, May 2026 concall OB upgrade; entry ₹320-345.",
        exit_trigger="Promoter pledge not resolved, IDL integration losses persist beyond FY27, DRDO program delays.",
        conviction=5,
    ),
    dict(
        sym="SUPREMEPWR", name="Supreme Power Equipment",
        why_holding=(
            "Transformer manufacturer with 9.3x order book growth in 28 months — inflection from demand-constrained to capacity-constrained. "
            "Kannur plant (220kV/200MVA) commissioned Feb 2026 unlocks a new product category and drives multiple expansion. "
            "Book-to-bill of 4.05x vs peers at 0.8-1.5x is extraordinary forward visibility."
        ),
        entry_trigger="Q4 FY26 results confirm execution + Kannur commercial revenue; entry ₹200-220.",
        exit_trigger="Order book cancellations, Kannur ramp disappoints, competitor capacity addition compresses margins.",
        conviction=4,
    ),
    dict(
        sym="ITC", name="ITC Limited",
        why_holding=(
            "FMCG conglomerate anchored by a dominant cigarettes business generating 80%+ of profits. "
            "Historically low PE with a reliable dividend yield; FMCG segment approaching profitability after years of investment. "
            "Hotels demerger is a re-rating catalyst as pure-play FMCG valuation emerges."
        ),
        entry_trigger="Trading near historical low PE (₹260-290 ideal zone); hotels demerger clarity.",
        exit_trigger="Cigarette tax hikes materially above inflation, FMCG EBITDA margins remain sub-8% beyond FY27.",
        conviction=4,
    ),
    dict(
        sym="HCG", name="HealthCare Global Enterprises",
        why_holding=(
            "India's leading cancer specialty hospital chain — KKR ownership driving operational improvements. "
            "Cancer care is a high-conviction structural growth sector with limited organised competition. "
            "Margin expansion story as existing centres mature and hit operating leverage."
        ),
        entry_trigger="KKR-driven margin improvement visible in 2-3 quarters; entry ₹570-610.",
        exit_trigger="KKR premature exit, cancer centre economics fail to scale, regulatory price caps on oncology.",
        conviction=4,
    ),
    dict(
        sym="NH", name="Narayana Hrudayalaya",
        why_holding=(
            "Cardiac and multi-specialty hospital chain with affordable-care model that has maintained 70%+ occupancy. "
            "Cayman Islands operations diversify revenue toward international patients (targeting 9% by FY27). "
            "Capital-intensive sector creates high barriers; established centres have strong operating leverage."
        ),
        entry_trigger="Cayman expansion revenue growth, ARPOB improvement; entry ₹1,600-1,750.",
        exit_trigger="GoI price caps on cardiac procedures (stent precedent), Cayman operations disappointed.",
        conviction=4,
    ),
    dict(
        sym="IEX", name="Indian Energy Exchange",
        why_holding=(
            "Largest power exchange in India — real-time power market (RTM) volumes growing as India's grid becomes more dynamic. "
            "Contra bet: MBED headwind is partially priced in; long-term power market deregulation favours exchanges. "
            "Asset-light business model with high cash conversion and no capex requirements."
        ),
        entry_trigger="RTM volume acceleration, regulatory clarity on MBED timeline; entry ₹100-110.",
        exit_trigger="MBED implementation materially cuts IEX's volume, alternative exchange gains market share.",
        conviction=3,
    ),
    dict(
        sym="SJSENTP", name="SJS Enterprises",
        why_holding=(
            "Automotive aesthetics — IML/IMD/chrome/cover glass — with multi-year contracts at Hero MotoCorp (₹250 cr) and Stellantis (8yr). "
            "High switching cost for OEMs once tooling is approved creates sticky revenue. "
            "Confirmed long-term holding with target ₹2,687 from research model."
        ),
        entry_trigger="Hero deal revenue ramp visible in Q1/Q2 FY27, Stellantis volumes start.",
        exit_trigger="Insider trading case adverse outcome, Hero contract not renewed, 2-wheeler slowdown sustained.",
        conviction=4,
    ),
    dict(
        sym="ATHERENERG", name="Ather Energy",
        why_holding=(
            "Premium EV scooter brand with 18.8% market share and Atherstack proprietary software platform as a tech moat. "
            "Factory 3.0 (Jul 2026) will triple capacity, enabling the scale needed for profitability. "
            "Confirmed long-term holding; loss-making phase — holding for the EV infrastructure buildout thesis."
        ),
        entry_trigger="Factory 3.0 ramp confirmation, EBITDA breakeven; existing position from ₹676.",
        exit_trigger="Market share loss to Ola/Hero EV, battery safety recall, Atherstack loses differentiation.",
        conviction=4,
    ),
    dict(
        sym="AEROFLEX", name="Aeroflex Industries",
        why_holding=(
            "Hose manufacturer transitioning to AI datacenter liquid cooling skids — Vertiv partnership as proof point. "
            "Datacenter liquid cooling is a 5-10x revenue opportunity vs core hose business. "
            "Swing trade candidate; core thesis requires Vertiv deal revenue to materialise."
        ),
        entry_trigger="Vertiv LC skids revenue in quarterly results, 20EMA re-entry on pullback.",
        exit_trigger="Vertiv relationship ends or is de-prioritised, LC skids market does not develop at expected pace.",
        conviction=3,
    ),
]


def main(user_id: int) -> None:
    db = SessionLocal()
    try:
        n_new = n_upd = 0
        for t in THESES:
            row = (
                db.query(InvestmentThesis)
                .filter(
                    InvestmentThesis.user_id == user_id,
                    InvestmentThesis.asset_type == "equity",
                    InvestmentThesis.sym == t["sym"],
                )
                .first()
            )
            if row is None:
                row = InvestmentThesis(
                    user_id=user_id,
                    asset_type="equity",
                    sym=t["sym"],
                )
                db.add(row)
                n_new += 1
            else:
                n_upd += 1
            row.name           = t["name"]
            row.why_holding    = t["why_holding"]
            row.entry_trigger  = t["entry_trigger"]
            row.exit_trigger   = t["exit_trigger"]
            row.conviction     = t["conviction"]
            row.review_date    = "2026-06-13"
            row.updated_at     = datetime.now(timezone.utc)
        db.commit()
        print(f"investment_thesis: {n_new} inserted, {n_upd} updated for user {user_id}")
    finally:
        db.close()


if __name__ == "__main__":
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    main(uid)
