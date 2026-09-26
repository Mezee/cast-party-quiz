// AUTO-GENERATED from the original Python question bank.
// Regenerate with: ./venv/bin/python tools/export_questions.py
import { mutation, query } from "./_generated/server";

export const BANK = [
  { cat: "Geography", text: "Which country has the most natural lakes?",
    options: ["Canada", "Russia", "Finland", "Brazil"], answer: 0 },
  { cat: "Science", text: "What is the most abundant gas in Earth's atmosphere?",
    options: ["Oxygen", "Carbon dioxide", "Nitrogen", "Argon"], answer: 2 },
  { cat: "Music", text: "Which instrument has 88 keys?",
    options: ["Organ", "Piano", "Accordion", "Harpsichord"], answer: 1 },
  { cat: "Movies", text: "Which film features the line “You're gonna need a bigger boat”?",
    options: ["Jaws", "Titanic", "The Perfect Storm", "Deep Blue Sea"], answer: 0 },
  { cat: "History", text: "In which year did the Berlin Wall fall?",
    options: ["1985", "1987", "1989", "1991"], answer: 2 },
  { cat: "Nature", text: "What is a group of flamingos called?",
    options: ["A flamboyance", "A murder", "A gaggle", "A parliament"], answer: 0 },
  { cat: "Space", text: "Which planet spins on its side?",
    options: ["Neptune", "Uranus", "Saturn", "Mercury"], answer: 1 },
  { cat: "Food", text: "Sushi originated in which country?",
    options: ["China", "Korea", "Japan", "Vietnam"], answer: 2 },
  { cat: "Tech", text: "What does “HTTP” stand for?",
    options: ["HyperText Transfer Protocol", "High Transfer Text Process", "Hyperlink Text Transmission Protocol", "Host Transfer Type Protocol"], answer: 0 },
  { cat: "Animals", text: "How many hearts does an octopus have?",
    options: ["One", "Two", "Three", "Five"], answer: 2 },
  { cat: "Geography", text: "Which is the longest river in the world?",
    options: ["Amazon", "Nile", "Yangtze", "Mississippi"], answer: 1 },
  { cat: "Sports", text: "How many players are on the field per team in soccer?",
    options: ["9", "10", "11", "12"], answer: 2 },
  { cat: "Art", text: "Who painted the Mona Lisa?",
    options: ["Michelangelo", "Raphael", "Leonardo da Vinci", "Donatello"], answer: 2 },
  { cat: "Science", text: "What is the hardest natural substance on Earth?",
    options: ["Quartz", "Diamond", "Titanium", "Obsidian"], answer: 1 },
  { cat: "Music", text: "Which band released the album “The Dark Side of the Moon”?",
    options: ["The Beatles", "Led Zeppelin", "Pink Floyd", "The Who"], answer: 2 },
  { cat: "Geography", text: "What is the smallest country in the world by area?",
    options: ["Monaco", "Nauru", "Vatican City", "San Marino"], answer: 2 },
  { cat: "Nature", text: "Which animal never sleeps?",
    options: ["Bullfrog", "Giraffe", "Dolphin", "Sloth"], answer: 0 },
  { cat: "History", text: "Who was the first person to walk on the Moon?",
    options: ["Buzz Aldrin", "Neil Armstrong", "Yuri Gagarin", "Michael Collins"], answer: 1 },
  { cat: "Tech", text: "What year was the first iPhone released?",
    options: ["2005", "2007", "2009", "2010"], answer: 1 },
  { cat: "Food", text: "Which spice is the most expensive by weight?",
    options: ["Vanilla", "Saffron", "Cardamom", "Cinnamon"], answer: 1 },
  { cat: "Movies", text: "Which movie won the first Academy Award for Best Picture?",
    options: ["Wings", "Metropolis", "Sunrise", "The Jazz Singer"], answer: 0 },
  { cat: "Animals", text: "What is the fastest land animal?",
    options: ["Lion", "Pronghorn", "Cheetah", "Greyhound"], answer: 2 },
  { cat: "Science", text: "What is the chemical symbol for gold?",
    options: ["Ag", "Au", "Gd", "Go"], answer: 1 },
  { cat: "Geography", text: "How many time zones does Russia span?",
    options: ["7", "9", "11", "13"], answer: 2 },
] as const;

export const seed = mutation({
  args: {},
  handler: async (ctx) => {
    const existing = await ctx.db.query("questions").first();
    if (existing) return { seeded: false, count: 0 };
    for (const q of BANK) {
      await ctx.db.insert("questions", {
        cat: q.cat,
        text: q.text,
        options: [...q.options],
        answer: q.answer,
      });
    }
    return { seeded: true, count: BANK.length };
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    const qs = await ctx.db.query("questions").collect();
    qs.sort((a, b) => a._creationTime - b._creationTime);
    return qs.map((q) => ({
      id: q._id,
      cat: q.cat,
      text: q.text,
      options: q.options,
      answer: q.answer,
    }));
  },
});
