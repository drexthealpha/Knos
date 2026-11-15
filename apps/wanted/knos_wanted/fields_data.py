"""The fields page: 7 bottlenecks by 7 technologies, 49 cells, each live or next,
the framework's 12 unlock pairs in its own words. Served at GET /api/fields."""
FIELDS = {
 "source": "the framework (22 Oct 2026): 7 bottlenecks, 7 technologies, and which technology solves which bottleneck",
 "rule": "next = the technology is not real at scale today (fusion or SMR baseload, room-temperature superconductors, quantum-designed catalysts, cognitive healthspan); live = a demand check of a real product works now",
 "bottlenecks": [
  {
   "id": "capital",
   "name": "Capital",
   "full": "Capital and commercialization: the valley of death"
  },
  {
   "id": "hardware",
   "name": "Hardware",
   "full": "Physical execution and hardware: the supply chain wall"
  },
  {
   "id": "energy",
   "name": "Energy",
   "full": "Energy and grid interconnection: the energization barrier"
  },
  {
   "id": "regulation",
   "name": "Regulation",
   "full": "Regulatory and bureaucratic inertia: permitting and policy"
  },
  {
   "id": "materials",
   "name": "Materials",
   "full": "Raw materials and geopolitical monopolies: critical dependencies"
  },
  {
   "id": "people",
   "name": "People",
   "full": "Human capital and skilled labor: the expertise deficit"
  },
  {
   "id": "resistance",
   "name": "Resistance",
   "full": "Institutional and societal resistance: NIMBYism and inertia"
  }
 ],
 "technologies": [
  {
   "id": "ai",
   "name": "AI"
  },
  {
   "id": "web3",
   "name": "Web3"
  },
  {
   "id": "quantum",
   "name": "Quantum"
  },
  {
   "id": "energy",
   "name": "Energy"
  },
  {
   "id": "biotech",
   "name": "Biotech"
  },
  {
   "id": "materials",
   "name": "Materials"
  },
  {
   "id": "pqc",
   "name": "PQC"
  }
 ],
 "cells": [
  {
   "b": "capital",
   "t": "ai",
   "title": "Paper plan",
   "idea": "an AI tool that turns a lab paper into an investor ready business plan",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "capital",
   "t": "web3",
   "title": "Milestone money, held",
   "idea": "milestone money held, released to the lab when the milestone check passes",
   "status": "live",
   "feature": "/app/#projects",
   "unlock": "DeSci, tokenized IP-NFTs and DAOs crowdsource risk capital; milestone-based smart contracts bypass legacy VC and bank timelines."
  },
  {
   "b": "capital",
   "t": "quantum",
   "title": "Quantum chemistry",
   "idea": "a quantum chemistry simulation service for early drug startups",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "capital",
   "t": "energy",
   "title": "Community solar",
   "idea": "a community solar subscription for small businesses",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "capital",
   "t": "biotech",
   "title": "Patient fund",
   "idea": "a crowdfunded rare disease research fund for patients",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "capital",
   "t": "materials",
   "title": "Carbon frame",
   "idea": "a recycled carbon fiber bike frame",
   "status": "live"
  },
  {
   "b": "capital",
   "t": "pqc",
   "title": "Safe cap-table",
   "idea": "a post-quantum secure cap table for startups",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "hardware",
   "t": "ai",
   "title": "Factory scheduler",
   "idea": "an AI factory scheduling tool for small machine shops",
   "feature": "/companies",
   "door": "companies",
   "status": "live",
   "unlock": "AI world models optimize factory schedules and simulate hardware configurations."
  },
  {
   "b": "hardware",
   "t": "web3",
   "title": "Tool library",
   "idea": "a shared tool library for makers with on chain deposits",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "hardware",
   "t": "quantum",
   "title": "Pipe sensor",
   "idea": "a quantum sensor for finding underground pipes",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "hardware",
   "t": "energy",
   "title": "Site battery",
   "idea": "a portable battery generator for construction sites",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "hardware",
   "t": "biotech",
   "title": "Mycelium packaging",
   "idea": "a mycelium packaging replacement for foam",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "hardware",
   "t": "materials",
   "title": "Cooling paint",
   "idea": "a passive radiative cooling paint for server rooms",
   "feature": "/companies",
   "door": "companies",
   "status": "live",
   "next_part": "room-temperature superconductors",
   "unlock": "Metamaterials, room-temperature superconductors and high-efficiency heat sinks cut hardware size."
  },
  {
   "b": "hardware",
   "t": "pqc",
   "title": "Safe firmware",
   "idea": "a post-quantum secure firmware update service for factory machines",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "ai",
   "title": "Bill cutter",
   "idea": "an AI tool that cuts home electricity bills",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "web3",
   "title": "Solar trading",
   "idea": "peer to peer neighborhood solar energy trading",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "quantum",
   "title": "Charging optimizer",
   "idea": "a quantum inspired battery charging optimizer",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "energy",
   "title": "Data-center reactor",
   "idea": "a small modular reactor for a data center",
   "feature": "/companies",
   "door": "companies",
   "status": "next",
   "unlock": "SMRs, microreactors and fusion give 24/7 on-site baseload; behind-the-meter power bypasses 3-5-year grid queues."
  },
  {
   "b": "energy",
   "t": "biotech",
   "title": "Algae fuel",
   "idea": "algae biofuel for backup generators",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "materials",
   "title": "Perovskite tile",
   "idea": "a perovskite solar roof tile for homes",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "energy",
   "t": "pqc",
   "title": "Safe meter",
   "idea": "a post-quantum secure smart meter",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "ai",
   "title": "Permit filler",
   "idea": "an AI assistant that fills building permit applications",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "web3",
   "title": "Research DAO",
   "idea": "a DAO that funds and governs open research",
   "feature": "/companies",
   "door": "companies",
   "status": "live",
   "unlock": "Permissionless governance for borderless capital and research."
  },
  {
   "b": "regulation",
   "t": "quantum",
   "title": "Regulator course",
   "idea": "an online quantum computing course for regulators",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "energy",
   "title": "Battery kit",
   "idea": "a pre approved home battery installation kit",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "biotech",
   "title": "Soil test kit",
   "idea": "a home test kit for soil contamination",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "materials",
   "title": "Timber panel",
   "idea": "a fire rated mass timber building panel",
   "status": "live"
  },
  {
   "b": "regulation",
   "t": "pqc",
   "title": "ZK audit",
   "idea": "a zero knowledge compliance audit trail for banks",
   "status": "live",
   "unlock": "Zero-knowledge proofs and cryptographically secure audit trails streamline automated compliance and regulatory verification."
  },
  {
   "b": "materials",
   "t": "ai",
   "title": "Supplier finder",
   "idea": "an AI tool that finds alternative suppliers for rare parts",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "materials",
   "t": "web3",
   "title": "Mineral tracing",
   "idea": "on chain traceability for conflict free minerals",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "materials",
   "t": "quantum",
   "title": "Platinum-free catalyst",
   "idea": "a quantum designed catalyst that replaces platinum",
   "status": "next",
   "unlock": "Quantum molecular simulation finds synthetic catalysts and alloys to replace rare minerals."
  },
  {
   "b": "materials",
   "t": "energy",
   "title": "Sodium-ion battery",
   "idea": "a sodium ion battery without lithium or cobalt",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "materials",
   "t": "biotech",
   "title": "Fermented protein",
   "idea": "precision fermented dairy protein",
   "feature": "/companies",
   "door": "companies",
   "status": "live",
   "unlock": "Precision fermentation synthesizes materials domestically."
  },
  {
   "b": "materials",
   "t": "materials",
   "title": "Rare-earth-free motor",
   "idea": "a rare earth free electric motor",
   "status": "live"
  },
  {
   "b": "materials",
   "t": "pqc",
   "title": "Supply ledger",
   "idea": "a post-quantum secure supply chain ledger",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "people",
   "t": "ai",
   "title": "Engineer copilot",
   "idea": "an AI copilot for power systems engineers",
   "status": "live",
   "unlock": "Autonomous AI does circuit layout, power-flow modeling and code as a force multiplier for engineers."
  },
  {
   "b": "people",
   "t": "web3",
   "title": "Skill credentials",
   "idea": "on chain verified skills credentials for electricians",
   "status": "live"
  },
  {
   "b": "people",
   "t": "quantum",
   "title": "Quantum course",
   "idea": "a quantum computing course for teenagers",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "people",
   "t": "energy",
   "title": "Electrician simulator",
   "idea": "a training simulator for high voltage electricians",
   "status": "live"
  },
  {
   "b": "people",
   "t": "biotech",
   "title": "Cognitive healthspan",
   "idea": "a supplement that extends cognitive healthspan",
   "feature": "/companies",
   "door": "companies",
   "status": "next",
   "unlock": "Biotech extends cognitive healthspan."
  },
  {
   "b": "people",
   "t": "materials",
   "title": "Machining glove",
   "idea": "a smart glove that teaches precision machining",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "people",
   "t": "pqc",
   "title": "PQC course",
   "idea": "a post-quantum cryptography course for developers",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "ai",
   "title": "Neighbor answers",
   "idea": "an AI tool that answers neighbors questions about a new project",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "web3",
   "title": "Community wind",
   "idea": "a community owned wind farm with local shares",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "quantum",
   "title": "Random key",
   "idea": "a quantum random number generator USB key",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "energy",
   "title": "Town microreactor",
   "idea": "a zero emission microreactor for a town",
   "feature": "/companies",
   "door": "companies",
   "status": "next",
   "live_part": "passive cooling",
   "unlock": "Zero-emission nuclear and passive cooling remove noise, heat and pollution concerns."
  },
  {
   "b": "resistance",
   "t": "biotech",
   "title": "Lab-grown leather",
   "idea": "a lab grown leather handbag",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "materials",
   "title": "Quiet module",
   "idea": "a quiet passive cooled data center module",
   "feature": "/companies",
   "door": "companies",
   "status": "live"
  },
  {
   "b": "resistance",
   "t": "pqc",
   "title": "Safe messaging",
   "idea": "a post-quantum encrypted messaging app",
   "feature": "/companies",
   "door": "companies",
   "status": "live",
   "unlock": "Post-quantum security gives zero-trust protection for utilities and national infrastructure."
  }
 ]
}
