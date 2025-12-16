import { Stack } from '@mui/material';
import ScopedCssBaseline from '@mui/material/ScopedCssBaseline';
import { ThemeProvider } from '@mui/material/styles';

import { customTheme } from '../common/theme';
import { IEnvironmentData } from './types';
import { EnvironmentList } from './EnvironmentList';
import { IMachineProfile, NewEnvironmentDialog } from './NewEnvironmentDialog';
import { AxiosContext } from '../common/AxiosContext';
import { useEffect, useMemo } from 'react';
import { AxiosClient } from '../common/axiosclient';
import { useJupyterhub } from '../common/JupyterhubContext';

export interface IAppProps {
  images: IEnvironmentData[];
  default_cpu_limit: string;
  default_mem_limit: string;
  machine_profiles: IMachineProfile[];
  use_binderhub: boolean;
  repo_providers?: { label: string; value: string }[];
}
export default function App(props: IAppProps) {
  const jhData = useJupyterhub();

  // Auto-reload while preparing
  useEffect(() => {
    const hasPreparing = props.images.some(img => img.status === 'preparing');
    if (!hasPreparing) return;

    const timer = setInterval(() => {
      window.location.reload();
    }, 5000);
    return () => clearInterval(timer);
  }, [props.images]);

  const serviceClient = useMemo(() => {
    const baseUrl = jhData.servicePrefix;
    const xsrfToken = jhData.xsrfToken;
    return new AxiosClient({ baseUrl, xsrfToken });
  }, [jhData]);

  return (
    <ThemeProvider theme={customTheme}>
      <AxiosContext.Provider value={{ serviceClient }}>
        <ScopedCssBaseline>
          <Stack sx={{ padding: 1 }} spacing={1}>
            <NewEnvironmentDialog
              default_cpu_limit={props.default_cpu_limit}
              default_mem_limit={props.default_mem_limit}
              machine_profiles={props.machine_profiles}
              use_binderhub={props.use_binderhub}
              repo_providers={props.repo_providers}
            />
            <EnvironmentList {...props} />
          </Stack>
        </ScopedCssBaseline>
      </AxiosContext.Provider>
    </ThemeProvider>
  );
}
