export const ENV_PREFIX = 'environments';
export interface IEnvironmentData {
  provider: string | null;
  image_name: string;
  cpu_limit: string;
  display_name: string;
  mem_limit: string;
  ref: string;
  repo: string;
  status: string;
  uid?: string;
}
