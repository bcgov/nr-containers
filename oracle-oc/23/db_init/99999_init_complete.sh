#!/bin/bash
# This file will dump a marker file to indicate that the init process is complete
# The existence of this file is tied into the health check process.  This
# allows subsequent stages in the dorker comp to wait until the init process
# is complete.
touch /opt/oracle/oradata/init_complete.marker
echo "Init process complete"