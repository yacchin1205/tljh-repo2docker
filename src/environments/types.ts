export const ENV_PREFIX = 'environments';
export interface IEnvironmentData {
  image_name: string;
  cpu_limit: string;
  display_name: string;
  creation_date: string;
  owner: string;
  mem_limit: string;
  ref: string;
  repo: string;
  status: string;
  uid?: string;
  buildargs?: string;
  // Older images and database entries may not have a provider.
  provider?: string | null;
  // An object from the DB (BinderHub backend), a serialized string from the
  // Docker label (local backend).
  node_selector?: { [key: string]: string } | string;
}

/**
 * Stable identifier, used as the grid row id. uid is absent on entries that
 * only exist as a Docker image.
 */
export function environmentId(it: IEnvironmentData): string {
  return it.uid ?? it.image_name;
}
