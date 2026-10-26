# VAREN TSC Meeting - <%= new Intl.DateTimeFormat('en-US', { dateStyle: 'long', timeZone: 'UTC' }).format(new Date(date.epochMilliseconds)) %>

## Date/Time

<% const timezones = [
  'America/Los_Angeles',
  'America/Denver',
  'America/Chicago',
  'America/New_York',
  'Europe/London',
  'Europe/Amsterdam',
  'Asia/Shanghai',
  'Asia/Tokyo',
]; %>
| Timezone | Date/Time |
|----------|-----------|
<%= timezones.map((zone) => {
  const zonedDate = date.toZonedDateTimeISO(zone)
  const formatter = new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: zone
  })
  const formattedDate = formatter.format(new Date(zonedDate.epochMilliseconds))
  return `| ${zone} | ${formattedDate} |`
}).join('\n') %>

Or in your local time:
https://www.timeanddate.com/worldclock/fixedtime.html?msg=<%= encodeURIComponent(title) %>&iso=<%= date.toZonedDateTimeISO('UTC').toPlainDateTime().toString().slice(0, 16).replace(/[-:]/g, '') %>&p1=1440&ah=1

All meetings are listed on the project calendar at https://lists.lfenergy.org/calendar, subject to the mailing lists you are subscribed to.

### Conference call details

_fill in Zoom details_

### Meeting recordings

_fill in recording details_

## Attendance

### Voting member rollcall:

* [ ] Mohamed Gaha (Lead)
* [ ] Patrick Lesage (Co-Lead)

### Other Attendees

## Agenda

Extracted from **<%= agendaLabel %>** labelled issues and pull requests from **<%= owner %>/<%= repo %>** prior to the meeting.

<%= agendaIssues.map((i) => {
  return `* ${i.title} [#${i.number}](${i.html_url})`
}).join('\n') %>

## Action Items

## Notes
