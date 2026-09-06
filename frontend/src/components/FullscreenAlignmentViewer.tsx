import { Box } from '@mui/material'
import { AlignmentViewer } from './AlignmentViewer'

type Props = {
  jobId: string
  groupName?: string
}

/** Полноэкранная страница просмотра выравнивания для отдельной вкладки. */
export function FullscreenAlignmentViewer({ jobId, groupName }: Props) {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AlignmentViewer jobId={jobId} groupName={groupName} fullScreen />
    </Box>
  )
}
