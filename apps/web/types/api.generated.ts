/**
 * This file is auto-generated from FastAPI's OpenAPI schema.
 * Run `npm run codegen` or `python scripts/generate_types.py` to regenerate.
 */

export interface Case {
  id: string;
  title: string;
  citation_number?: string;
  jurisdiction: string;
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: string;
  case_id: string;
  filename: string;
  file_size: number;
  mime_type: string;
  gcs_uri: string;
  status: 'pending' | 'processing' | 'indexed' | 'failed';
  created_at: string;
}

export interface ExecutionTask {
  id: string;
  agent_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: Record<string, unknown>;
  error?: string;
}

export interface AgentExecution {
  id: string;
  case_id: string;
  user_prompt: string;
  status:
    | 'pending'
    | 'interpreting'
    | 'waiting_for_input'
    | 'planning'
    | 'running'
    | 'retrying'
    | 'validating'
    | 'completed'
    | 'failed'
    | 'cancelled';
  tasks: ExecutionTask[];
  clarification_needed?: boolean;
  clarification_question?: string;
  synthesis_output?: string;
  created_at: string;
}
