# How to Calculate the Cost of Rework

> **Review status:** Published
> **Proposed public path:** `/articles/cost-of-rework`
> **Primary search intent:** Estimate the annual labor and documented nonlabor cost of rework
> **Methodology:** `docs/utilities/Jaspen_Rework_Cost_Calculator_Methodology_v1.xlsx`
> **Natural next step:** [Calculate the cost of rework](https://jaspen.ai/tools/rework-cost-calculator)

Rework is any work that had already crossed an invisible finish line. Someone called it done, ready to ship, ready to approve, ready to hand off. Then it had to be corrected, rebuilt, reprocessed, or simply done over.

That’s what makes rework so slippery. Everyone on the team can feel it, but almost nobody counts it. It hides inside revision loops, reopened tickets, repeat approvals, the manager hours spent smoothing it over, remade materials, and slipped deadlines. If you want to put a real number on it, the first job isn’t math. It’s drawing a boundary around what you’re actually counting.

## What actually counts as rework?

Before you measure anything, agree on what rework means, or the number won’t mean much. For this model, rework is time or resources spent correcting, revising, rebuilding, reprocessing, or repeating work that was already considered finished or ready to move forward.

Notice what that leaves out. It isn’t ordinary first-pass work, and it isn’t every revision. Some iteration is how good work gets made: drafts, reviews, deliberate experiments. The test is whether the effort repeated something the organization already believed had cleared the bar.

In practice, rework tends to look like:

- rebuilding a deliverable after the requirements were misunderstood;
- re-entering or reconciling data after a handoff error that could have been prevented;
- remaking a physical item that failed an agreed spec;
- reopening approved work because a decision never got written down; or
- running another review cycle because the right person weighed in too late.

Write the definition to fit how your team actually works. And resist the urge to stretch it just to make the total look bigger. A number you inflated is a number you can’t defend.

## How do you turn rework into hours and dollars?

Start with time, using your own numbers. First, figure out how many hours your team is paid for in a year: headcount, times paid hours per week, times the weeks they work. Multiply that by your best estimate of the share of time spent on rework, and you have rework hours. Multiply those hours by your fully loaded hourly cost, and you have the direct labor cost of rework.

Everything hinges on that rework share, and it isn’t something to pull from an industry chart. Ground it in something real: a time study, ticket history, quality records, workflow data, or a careful internal review. It’s an estimate either way, but an estimate with evidence behind it is one you can stand on.

## What else belongs in the number?

Contributor time is the core, but it’s rarely the whole cost.

**Manager coordination.** Rework pulls managers in too, to re-review, re-approve, and untangle things. Count their rework hours per week across the working year, at their own loaded rate.

**Materials and vendors.** Add known nonlabor costs, like remade materials or an outside vendor’s charge to redo something.

**Delay cost, but only if you can document it.** If a slip has a real, defensible dollar figure attached, include it. If it doesn’t, leave it at zero. A delay you suspect but can’t measure is not a license to invent a number. Add these to the direct labor and you have your gross annual rework cost.

## How much of it could you actually recover?

Here’s where a lot of cost estimates overreach. Not every dollar of rework is avoidable. Some churn is baked into complex work, and some fixes would cost more than the failures they prevent. So take your gross cost and multiply it by the share you honestly believe is addressable.

Be precise about what that gives you. It’s a planning boundary, not a promise. It says: of the cost we modeled, this is the slice we think we could influence. It does not say any particular tool, manager, or process change will actually recover it.

The same restraint applies if you translate rework hours into full-time equivalents by dividing the hours by the annual hours of one full-time employee. That makes the scale intuitive (“this is like two people working on nothing but redo work”). It is not a recommendation to cut two jobs.

## What does this look like with real numbers?

Let’s make it concrete. Take a 12-person team working 40 paid hours a week for 48 weeks a year, at a fully loaded cost of $65 an hour, and estimate that 8 percent of their time goes to rework. Add three manager hours a week at $95, $12,000 in known material and vendor costs, and no documented delay cost.

Run the model and you get:

- **1,843 rework hours** a year;
- about **$119,808** in direct rework labor;
- **$13,680** in manager coordination;
- **$145,488** in gross annual rework cost once you add the material costs; and
- **$72,744** as the addressable portion, if you set the avoidable share at 50 percent.

Because several inputs are estimates, it’s honest to show a range too. At a 25 percent uncertainty band, the gross cost runs roughly **$109,116 to $181,860**.

Every one of those figures traces back to an input you chose. None of them is a claim about what a typical 12-person team spends.

## What about the savings from fixing it?

Once you can see the addressable cost, it’s natural to ask what improving things might be worth. You can model that by multiplying the addressable cost by a reduction you want to test. In the example above, trimming addressable rework by 10, 25, or 50 percent would be worth about $7,274, $18,186, or $36,372.

Just hold those loosely. Every one of them is conditional: only if the modeled cost is right, only if the avoidable share is reasonable, and only if you actually hit that reduction. They’re illustrations of what recovery could be worth, not forecast savings, and certainly not money any specific tool will hand you.

## Can you just use an industry benchmark?

It’s tempting to skip the internal work and grab a published rework percentage. Resist that. Outside research is good for defining categories, learning how others measure, and confirming that rework is worth taking seriously. It’s a poor substitute for your own rework rate.

Take a well-known figure: PMI found that 5.1 percent of project and program spending was wasted on poor requirements management in its 2014 survey ([PMI requirements-management research](https://www.pmi.org/learning/library/requirements-management-survey-13449)). That’s a real, specific finding about requirements practices. It is not a universal rework rate, and dropping it into every company’s calculator as a default would be a mistake. Use outside numbers as context, and your own measurements as the inputs.

## What should you double-check before you trust it?

Before you rely on the result, walk it through these:

- What event marks work as “done” or “ready to advance” in the first place?
- Which revisions are healthy iteration, and which are genuinely rework?
- How was the rework share estimated?
- Does the loaded hourly cost include benefits and employer costs?
- Is manager coordination already sitting inside the team’s rework hours?
- Are the material and vendor charges documented?
- Is the delay cost actually known, or just suspected?
- What evidence backs the avoidable-share assumption?
- Which specific change would affect which kind of rework?
- How will you measure improvement without quietly redefining the baseline?

## Why build the number this way?

A rework estimate earns its keep by being legible, not by being large. The moment the total breaks into contributor time, manager coordination, known nonlabor cost, and documented delay, the conversation changes. People stop arguing about whether the headline feels right and start examining the specific parts they doubt.

[Jaspen’s Rework Cost Calculator](https://jaspen.ai/tools/rework-cost-calculator) builds exactly that breakdown, with deterministic math and assumptions anyone can edit. Change the rework share and the arithmetic still holds. Separate gross cost from the portion you think is avoidable, and the boundary stays explicit. It won’t diagnose why the work keeps coming back, and it won’t promise you can recover a dollar of it. What it gives your team is a shared, inspectable starting point, the same picture to point at while you finally ask why finished work keeps landing back on the to-do list.
