// Marketing content + testimonials for Claus IA (bilingual it/en, fallback en).

const REVIEWS = {
  it: [
    { name: "Giulia Marchetti", role: "Content Strategist", text: "Claus IA ha rivoluzionato il mio lavoro: risposte istantanee, precise e brillanti. Non torno più indietro.", rating: 5 },
    { name: "Marco De Santis", role: "Founder & CEO", text: "Più veloce e più intelligente di qualsiasi altra IA che ho provato. Il piano Pro vale ogni centesimo.", rating: 5 },
    { name: "Sara Bianchi", role: "Sviluppatrice", text: "Scrive codice pulito, spiega tutto e cerca sul web in tempo reale. È come avere un senior al mio fianco.", rating: 5 },
    { name: "Luca Ferrari", role: "Studente universitario", text: "Mi salva ogni giorno per studio e progetti. Le immagini generate sono spettacolari.", rating: 5 },
    { name: "Elena Russo", role: "Marketing Manager", text: "Interfaccia bellissima, 15 lingue, dettatura vocale. Semplicemente perfetta.", rating: 5 },
    { name: "Davide Conti", role: "Product Designer", text: "Il Ragionamento Avanzato del Pro è impressionante: risposte ponderate e complete. Consigliatissimo.", rating: 5 },
  ],
  en: [
    { name: "Julia Marsh", role: "Content Strategist", text: "Claus IA transformed how I work: instant, precise, brilliant answers. I'm never going back.", rating: 5 },
    { name: "Mark Danes", role: "Founder & CEO", text: "Faster and smarter than any other AI I've tried. The Pro plan is worth every cent.", rating: 5 },
    { name: "Sara White", role: "Software Developer", text: "It writes clean code, explains everything and searches the web in real time. Like a senior by my side.", rating: 5 },
    { name: "Luke Ferris", role: "University Student", text: "Saves me every day for study and projects. The generated images are stunning.", rating: 5 },
    { name: "Helen Ross", role: "Marketing Manager", text: "Gorgeous interface, 15 languages, voice dictation. Simply perfect.", rating: 5 },
    { name: "David Cohen", role: "Product Designer", text: "Pro's Advanced Reasoning is impressive: thoughtful, complete answers. Highly recommended.", rating: 5 },
  ],
};

const STATS = {
  it: [
    { value: "1.2M+", label: "messaggi generati" },
    { value: "180+", label: "paesi" },
    { value: "4.9/5", label: "valutazione media" },
    { value: "15", label: "lingue" },
  ],
  en: [
    { value: "1.2M+", label: "messages generated" },
    { value: "180+", label: "countries" },
    { value: "4.9/5", label: "average rating" },
    { value: "15", label: "languages" },
  ],
};

export function getReviews(lang) { return REVIEWS[lang] || REVIEWS.en; }
export function getStats(lang) { return STATS[lang] || STATS.en; }
