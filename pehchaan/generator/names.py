"""Reference data for the synthetic generator.

Each canonical name maps to spellings that real Indian records actually use.
The first entry is the canonical spelling. The generator picks variants so the
matching engine has to recognise that "Laxmi" and "Lakshmi" are the same name.
"""

MALE_FIRST = {
    "karthik": ["karthik", "karthick", "kartik"],
    "mohammed": ["mohammed", "mohammad", "muhammad", "mohd"],
    "sriram": ["sriram", "shriram", "sreeram"],
    "deepak": ["deepak", "dipak"],
    "suresh": ["suresh"],
    "vijay": ["vijay", "vijai"],
    "rajesh": ["rajesh"],
    "anand": ["anand", "aanand"],
    "sanjay": ["sanjay", "sanjai"],
    "harish": ["harish", "hareesh"],
    "naveen": ["naveen", "navin"],
    "praveen": ["praveen", "pravin"],
    "nikhil": ["nikhil", "nikil"],
    "ganesh": ["ganesh"],
    "arjun": ["arjun"],
    "rahul": ["rahul"],
    "abdul": ["abdul", "abdhul"],
    "imran": ["imran"],
    "saravanan": ["saravanan", "sharavanan"],
    "krishna": ["krishna", "krisna"],
    "shyam": ["shyam", "syam"],
    "yogesh": ["yogesh"],
    "amit": ["amit"],
    "rohit": ["rohit"],
    "manoj": ["manoj"],
    "arun": ["arun"],
    "balaji": ["balaji"],
    "gopal": ["gopal", "gopaal"],
    "srinivasan": ["srinivasan", "sreenivasan", "shrinivasan"],
    "subramanian": ["subramanian", "subramaniam", "subramanyam"],
    "venkatesh": ["venkatesh"],
    "ramesh": ["ramesh"],
}

FEMALE_FIRST = {
    "lakshmi": ["lakshmi", "laxmi", "lakshmy"],
    "priya": ["priya", "priyaa"],
    "pooja": ["pooja", "puja"],
    "divya": ["divya", "dhivya"],
    "aishwarya": ["aishwarya", "aishwariya", "ishwarya"],
    "geetha": ["geetha", "gita", "geeta"],
    "anitha": ["anitha", "anita"],
    "kavitha": ["kavitha", "kavita"],
    "deepa": ["deepa", "dipa"],
    "meena": ["meena", "mina"],
    "sneha": ["sneha"],
    "fatima": ["fatima", "fathima"],
    "ayesha": ["ayesha", "aisha"],
    "swati": ["swati", "swathi"],
    "nandini": ["nandini"],
    "revathi": ["revathi", "revati"],
    "shalini": ["shalini", "salini"],
    "radha": ["radha"],
    "sunita": ["sunita", "sunitha"],
    "neha": ["neha"],
    "anjali": ["anjali"],
    "keerthana": ["keerthana", "kirthana"],
    "bhavana": ["bhavana", "bhavna"],
    "sowmya": ["sowmya", "soumya", "saumya"],
}

# Surname-style naming (common across North, East, West and parts of South India)
SURNAMES = {
    "sharma": ["sharma", "sarma"],
    "gupta": ["gupta"],
    "patel": ["patel"],
    "singh": ["singh"],
    "verma": ["verma"],
    "joshi": ["joshi"],
    "agarwal": ["agarwal", "aggarwal", "agrawal"],
    "choudhary": ["choudhary", "chaudhary", "chowdhury"],
    "banerjee": ["banerjee", "banerji"],
    "mukherjee": ["mukherjee", "mukherji"],
    "das": ["das"],
    "khan": ["khan"],
    "shaikh": ["shaikh", "sheikh"],
    "reddy": ["reddy", "reddi"],
    "nair": ["nair"],
    "menon": ["menon"],
    "pillai": ["pillai"],
    "rao": ["rao"],
    "naidu": ["naidu"],
    "shetty": ["shetty", "shetti"],
    "kulkarni": ["kulkarni"],
    "deshpande": ["deshpande"],
    "iyer": ["iyer", "aiyer"],
}

# Street pieces. Each tuple: (canonical, variants used in messy records)
STREET_TYPES = [("road", ["road", "rd", "rd."]), ("nagar", ["nagar", "ngr"]),
                ("street", ["street", "st", "st."]), ("main road", ["main road", "main rd"]),
                ("cross", ["cross", "crs"]), ("layout", ["layout", "lyt"])]
STREET_NAMES = ["gandhi", "nehru", "anna", "mg", "rajaji", "patel", "tagore", "ambedkar",
                "kamaraj", "shivaji", "indira", "subhash", "vivekananda", "lal bahadur",
                "sardar", "netaji", "bharathi", "periyar", "tilak", "ashok"]
AREAS = [("adyar", "600020"), ("t nagar", "600017"), ("koramangala", "560034"),
         ("indiranagar", "560038"), ("andheri east", "400069"), ("powai", "400076"),
         ("salt lake", "700091"), ("banjara hills", "500034"), ("kothrud", "411038"),
         ("velachery", "600042"), ("whitefield", "560066"), ("rohini", "110085"),
         ("dwarka", "110075"), ("gachibowli", "500032"), ("anna nagar", "600040")]

EMAIL_DOMAINS = ["mail.example", "inbox.example", "post.example"]
