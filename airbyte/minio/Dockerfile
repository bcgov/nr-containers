FROM minio/mc:latest@sha256:aead63c77f9db9107f1696fb08ecb0faeda23729cde94b0f663edf4fe09728e3

RUN mkdir /.mc

RUN chgrp -R 0 /.mc

RUN chmod -R g=u /.mc
