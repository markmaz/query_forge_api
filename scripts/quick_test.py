
import spacy

nlp = spacy.load("models/tier2_ner_v1_stable")

tests = [
    "How many EL students were chronically absent last year?",
    "Average math scores for 5th grade Hispanic students",
    "Attendance rate by school this year",
    "Suspension rate for students with disabilities",
    "what county has the 5th most students",
    "what is the average number of students per teacher, by county",
    "what is the minimum number of students per teacher",
    "Does Nashville offer more classes than Lynchburg",
    "what are the top 10 schools in terms of year over year student population growth over the last 5 years",
    "how many students appear in more than one district",
    "what class has the highest rate of skips"
]

for text in tests:
    doc = nlp(text)
    print("\nPrompt:", text)
    for ent in doc.ents:
        print(ent.text, "->", ent.label_)
