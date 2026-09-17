# Acknowledgements

People outside the project who reported a gap, a correction, or an error worth
acting on. Coverage grows fastest through the people who use the directory and
notice what is missing from it, and that work deserves a name against it.

Listing someone here records what they contributed. It is not an endorsement of
any organisation they work for, and it does not imply that a source they
suggested was adopted — where it was not, the entry says so and why.

Corrections and takedown requests are logged separately in
[takedowns.md](takedowns.md).

---

## 2026-09-16 — Randy Palmer

Wrote in about the peer-support listings for California and pointed out that
SUCCURRO carried nothing for LGBTQ+-affirming substance use and mental health
treatment.

He was right, and the cause was not an oversight in curation. The
findtreatment.gov locator export the dataset is built on carries 23
special-population codes — veterans, HIV/AIDS, trauma, PTSD, seniors — and none
for LGBTQ+ clients; the locator API rejects the code outright. Nothing in the
primary source could have produced those listings.

SAMHSA does still collect it. The annual N-SUMHSS survey asks whether a facility
runs a program or group specifically tailored for LGBT clients (category `SG`,
code `GL`) and publishes the answers facility-by-facility in the two National
Directories. Those are now a source (`samhsa/nsumhss-directory`), and 4,846
treatment facilities carry the `lgbtq-affirming` token as a result — 504 of them
in California.

The directory he suggested was not adopted: it discloses that it "receives
advertising payments from the treatment centers that respond to calls made to
the toll-free numbers listed on this website," which puts it outside what this
project will put in front of someone looking for treatment. The gap he
identified was real regardless, and finding it took reading the listings
carefully enough to notice an absence.
