# wavefront-ansible

Ansible roles and library helpers to facilitate working with WF


# Library Helpers

### wf_alert

Enables interfacing with reading wf alerts

```
# Read the output of an alert as it is in WF
wf_alert:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    alert_id: some-alert-id
```

### wf_source

Enables interfacing with the Wavefront API to create a source and tags

```
# Create/update a source with the specified tags/description
wf_source:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    source: some-wf-source
    description: "primary app server for try cluster"
    tags:
        - prod

# Hide a source
wf_source:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    source: some-wf-source
    hidden: True

    # If tags or description are specified they will update the source
    # Otherwise we don't touch these as part of hiding a source
```

### wf_source_tags

Enables interfacing with the Wavefront API to configure source tags

```
# Remove the prod tag from a source
wf_source_tags:
    token: your-api-token
    endpoint: hhttps://yourCluster.wavefront.com
    source: some-wf-source
    state: absent
    tags:
        - prod

# Add retired tag to a source
wf_source_tags:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    source: try-2a-app15-i-0a04798b7fef872c9
    state: present
    tags:
        - retired

# Get all tags for a source
wf_source_tags:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    source: some-wf-source
register: source_tags

debug:
  var: source_tags.tags

# Replace tags for a given source with new tags
wf_source_tags:
    token: your-api-token
    endpoint: https://yourCluster.wavefront.com
    source: some-wf-source
    state: replace
    tags:
        - prod
        - dc-3
        - closet-14
        - rack-21
        - webserver
        - nginx
```