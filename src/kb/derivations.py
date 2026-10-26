"""Derived nouns whose Porter stem differs from their base verb's stem.

Porter stemming gives "retain" and "retention" different stems, and so with
"decide" and "decision", and "divide" and "division". Each entry maps a derived
noun to its base verb, so both forms index and match under the verb's stem.

An entry whose noun and verb already share a stem is dead. Stemming already
conflates them, so the entry changes no term. A test rejects dead entries.

A noun whose common meaning is unrelated to its verb is excluded, because the
entry would merge different words in the content. Examples: "application"
(software, not "apply") and "formation" (not "form", as in a web form).

The list covers common verb-noun pairs, not any particular document set.
"""

BASE_FORMS = {
    "abstention": "abstain",
    "admission": "admit",
    "attention": "attend",
    "competition": "compete",
    "collision": "collide",
    "comparison": "compare",
    "conception": "conceive",
    "conclusion": "conclude",
    "conversion": "convert",
    "creation": "create",
    "decision": "decide",
    "deception": "deceive",
    "deduction": "deduce",
    "definition": "define",
    "description": "describe",
    "detention": "detain",
    "diversion": "divert",
    "division": "divide",
    "emission": "emit",
    "erosion": "erode",
    "evasion": "evade",
    "exclusion": "exclude",
    "explanation": "explain",
    "explosion": "explode",
    "expansion": "expand",
    "extension": "extend",
    "inclusion": "include",
    "induction": "induce",
    "intention": "intend",
    "introduction": "introduce",
    "inversion": "invert",
    "invasion": "invade",
    "maintenance": "maintain",
    "occurrence": "occur",
    "omission": "omit",
    "permission": "permit",
    "perception": "perceive",
    "persuasion": "persuade",
    "prescription": "prescribe",
    "production": "produce",
    "provision": "provide",
    "reception": "receive",
    "recognition": "recognize",
    "reduction": "reduce",
    "reliance": "rely",
    "repetition": "repeat",
    "retention": "retain",
    "seduction": "seduce",
    "subscription": "subscribe",
    "submission": "submit",
    "transmission": "transmit",
}
