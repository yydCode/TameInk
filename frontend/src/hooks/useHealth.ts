import { useQuery } from "@tanstack/react-query";

import { getHealth } from "../api/client";
import { queryKeys } from "../app/queryKeys";

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => getHealth(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });
}
