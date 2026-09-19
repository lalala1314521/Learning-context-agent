export type PageKey = "home" | "materials" | "knowledge" | "galaxy" | "ask" | "review";

export type GraphNode = {
  id: string;
  graph_id?: string;
  label: string;
  note?: string;
  node_type?: string;
  parent_id?: string | null;
  related_nodes?: string[];
  concept_id?: string | null;
  concept_label?: string | null;
  evidence?: string;
};

export type Graph = {
  id: string;
  title: string;
  description?: string;
  graph_type?: string;
  source_name?: string;
  source_type?: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
};

export type GraphDetail = {
  graph: Graph;
  nodes: GraphNode[];
  concept_links?: ConceptLink[];
  links?: Array<{ id: string; from_node_id: string; to_node_id: string; relation_type?: string; note?: string }>;
  structure?: { version: string; edges?: Array<{ id: string; from: string; to: string; relation_type?: string; status?: string; evidence?: string; cross_graph?: boolean }> };
};

export type Concept = {
  id: string;
  canonical_label: string;
  description?: string;
  domain_id?: string | null;
  mention_count?: number;
  mastery?: { mastery?: string; retrievability?: number | null; review_count?: number };
};

export type ConceptLink = {
  id: string;
  from_concept: string;
  to_concept: string;
  relation_type?: string;
  confidence?: number;
  status?: string;
  evidence?: string;
};

export type Domain = { id: string; name: string; color?: string; concept_count?: number };

export type GalaxyData = { concepts: Concept[]; links: ConceptLink[]; domains: Domain[] };

export type AskResult = {
  question: string;
  answer: string;
  sources: Array<{ type?: string; id?: string; graph_id?: string; title?: string; snippet?: string; source_name?: string; url?: string; node_id?: string }>;
  has_sources: boolean;
  web_fallback_used?: boolean;
};
