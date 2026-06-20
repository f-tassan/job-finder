// Curated catalog of PIF (Public Investment Fund) portfolio companies and their
// careers sites, used to pre-populate the portal-logins page. The user clicks a
// company's link to create an account on its site, then types their own
// username/password here. URLs open the company's careers/home page; if a deep
// careers path has moved, the link still lands on the right company site.

export interface PifCompany {
  name: string;
  sector: string;
  url: string;
}

export const PIF_SECTORS = [
  "Giga-projects & Real Estate",
  "Energy, Mining & Industrials",
  "Tech & Mobility",
  "Financial",
  "Telecom & Media",
  "Aviation & Logistics",
  "Healthcare & Consumer",
] as const;

export const PIF_COMPANIES: PifCompany[] = [
  // Giga-projects & Real Estate
  { name: "NEOM", sector: "Giga-projects & Real Estate", url: "https://www.neom.com/en-us/careers" },
  { name: "Red Sea Global", sector: "Giga-projects & Real Estate", url: "https://www.redseaglobal.com/en/careers" },
  { name: "ROSHN", sector: "Giga-projects & Real Estate", url: "https://www.roshn.sa/en/careers" },
  { name: "Qiddiya", sector: "Giga-projects & Real Estate", url: "https://qiddiya.com/careers" },
  { name: "Diriyah Company", sector: "Giga-projects & Real Estate", url: "https://www.diriyah.sa/en/careers" },
  { name: "KAFD", sector: "Giga-projects & Real Estate", url: "https://www.kafd.sa" },
  { name: "National Housing Company (NHC)", sector: "Giga-projects & Real Estate", url: "https://www.nhc.sa" },
  { name: "SEVEN", sector: "Giga-projects & Real Estate", url: "https://seven.sa" },
  { name: "Cruise Saudi", sector: "Giga-projects & Real Estate", url: "https://cruisesaudi.com" },

  // Energy, Mining & Industrials
  { name: "Saudi Aramco", sector: "Energy, Mining & Industrials", url: "https://www.aramco.com/en/careers" },
  { name: "SABIC", sector: "Energy, Mining & Industrials", url: "https://www.sabic.com/en/careers" },
  { name: "Ma'aden", sector: "Energy, Mining & Industrials", url: "https://www.maaden.com.sa/en/careers" },
  { name: "ACWA Power", sector: "Energy, Mining & Industrials", url: "https://acwapower.com/en/careers" },
  { name: "Saudi Electricity Company", sector: "Energy, Mining & Industrials", url: "https://www.se.com.sa" },
  { name: "Tarshid", sector: "Energy, Mining & Industrials", url: "https://www.tarshid.com.sa" },
  { name: "SAMI", sector: "Energy, Mining & Industrials", url: "https://www.sami.com.sa/en/careers" },
  { name: "Dussur", sector: "Energy, Mining & Industrials", url: "https://www.dussur.com" },

  // Tech & Mobility
  { name: "Lucid Motors", sector: "Tech & Mobility", url: "https://www.lucidmotors.com/careers" },
  { name: "Ceer", sector: "Tech & Mobility", url: "https://www.ceer.com" },
  { name: "Alat", sector: "Tech & Mobility", url: "https://alat.com" },
  { name: "HUMAIN", sector: "Tech & Mobility", url: "https://humain.ai" },
  { name: "SITE", sector: "Tech & Mobility", url: "https://site.sa" },

  // Financial
  { name: "Saudi National Bank (SNB)", sector: "Financial", url: "https://www.alahli.com" },
  { name: "Saudi Tadawul Group", sector: "Financial", url: "https://www.saudiexchange.sa" },
  { name: "Sanabil Investments", sector: "Financial", url: "https://www.sanabil.com" },

  // Telecom & Media
  { name: "stc", sector: "Telecom & Media", url: "https://www.stc.com.sa" },
  { name: "SRMG", sector: "Telecom & Media", url: "https://www.srmg.com" },

  // Aviation & Logistics
  { name: "Riyadh Air", sector: "Aviation & Logistics", url: "https://www.riyadhair.com/careers" },
  { name: "AviLease", sector: "Aviation & Logistics", url: "https://www.avilease.com" },

  // Healthcare & Consumer
  { name: "NUPCO", sector: "Healthcare & Consumer", url: "https://www.nupco.com" },
  { name: "Lifera", sector: "Healthcare & Consumer", url: "https://www.lifera.com" },
  { name: "SALIC", sector: "Healthcare & Consumer", url: "https://salic.com" },
];

// The credential storage key for a company: the URL host without a leading www.
// (mirrors the backend's tenant_key normalization).
export function companyHost(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}
